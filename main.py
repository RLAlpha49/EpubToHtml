"""
EPUB to HTML Converter

This module converts EPUB files to single HTML files with embedded or extracted images.
Supports various output formats and image handling strategies.
"""

import argparse
import base64
import logging
import sys
from pathlib import Path
from urllib.parse import quote

import ebooklib
from ebooklib import epub
from tqdm import tqdm

# Module logger (logging configuration moved to main() function)
logger = logging.getLogger(__name__)


class ImageHandler:
    """Handles image extraction and embedding strategies."""

    def __init__(
        self,
        strategy: str = "embed",
        output_dir: Path | None = None,
        html_root: Path | None = None,
        allow_unknown_mime: bool = False,
    ):
        """
        Initialize the image handler.

        Args:
            strategy: "embed" for base64 embedding, "extract" for file-based storage
            output_dir: Directory for extracted images (required if strategy is "extract")
            html_root: Root directory for HTML file (required if strategy is "extract" for relative path computation)
            allow_unknown_mime: Whether to allow embedding images with unknown MIME types (defaults to application/octet-stream)
        """
        self.strategy = strategy
        self.output_dir = output_dir
        self.html_root = html_root
        self.allow_unknown_mime = allow_unknown_mime
        self.image_map: dict[str, str] = {}
        self.basename_map: dict[str, list[tuple[str, str]]] = {}
        self.image_counter = 0

        if strategy == "extract" and not output_dir:
            raise ValueError("output_dir required when using 'extract' strategy")
        if strategy == "extract" and not html_root:
            raise ValueError(
                "html_root required when using 'extract' strategy for relative path computation"
            )

    def process_image(self, item) -> tuple[str, str]:
        """
        Process an image item from the EPUB.

        Args:
            item: The EPUB image item

        Returns:
            tuple of (image_name, image_reference)
        """
        if self.strategy == "embed":
            return self._embed_image(item)
        if self.strategy == "extract":
            return self._extract_image(item)
        raise ValueError(f"Unknown strategy: {self.strategy}")

    @staticmethod
    def _encode_url_path(posix_path: str) -> str:
        """
        Encode a POSIX path for use in HTML src attributes.

        Splits the path by '/', URL-encodes each segment, and rejoins.
        Preserves forward slashes (not encoded) for proper path structure.
        Handles spaces, unicode characters, and special characters.

        Args:
            posix_path: A POSIX-style path (e.g., 'folder/image name.png')

        Returns:
            URL-encoded path safe for HTML attributes (e.g., 'folder/image%20name.png')
        """
        # Split on forward slash and encode each segment separately
        # This preserves the path structure while encoding special characters
        segments = posix_path.split("/")
        encoded_segments = [quote(segment, safe="") for segment in segments]
        return "/".join(encoded_segments)

    def _embed_image(self, item) -> tuple[str, str]:
        """Convert image to base64 data URL.

        Raises:
            ValueError: If media type cannot be determined and allow_unknown_mime is False.
            RuntimeError: If media type cannot be determined and allow_unknown_mime is True,
                indicating extraction strategy should be used instead.
        """
        import mimetypes  # pylint: disable=import-outside-toplevel

        image_name = item.get_name()
        image_data = item.get_content()
        base64_data = base64.b64encode(image_data).decode("utf-8")

        # Determine media type with fallback mapping for common image types
        media_type = item.media_type
        if not media_type:
            media_type = mimetypes.guess_type(image_name)[0]

        # Map common image extensions if media type still unknown
        if not media_type:
            ext = Path(image_name).suffix.lower()
            extension_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".svg": "image/svg+xml",
                ".webp": "image/webp",
            }
            media_type = extension_map.get(ext)

        # If still unknown, check user preference for handling unknown MIME types
        if not media_type:
            if not self.allow_unknown_mime:
                error_msg = (
                    f"Cannot determine media type for image '{image_name}'. "
                    f"Use '--allow-unknown-mime' to skip type detection, "
                    f"or use '--strategy extract' to save images as files instead."
                )
                raise ValueError(error_msg)
            # Raise RuntimeError to trigger extraction fallback
            error_msg = (
                f"Unknown media type for image '{image_name}'. "
                f"Embedding with unknown MIME types is not recommended. "
                f"Use '--strategy extract' to save images as separate files instead."
            )
            logger.warning(error_msg)
            raise RuntimeError(error_msg)

        image_url = f"data:{media_type};base64,{base64_data}"

        self.image_map[image_name] = image_url

        # Also map by lowercase basename for lookup flexibility using multimap
        basename = Path(image_name).name.lower()
        if basename not in self.basename_map:
            self.basename_map[basename] = []
        self.basename_map[basename].append((image_name, image_url))

        logger.debug("Embedded image: %s (media type: %s)", image_name, media_type)
        return image_name, image_url

    def _extract_image(self, item) -> tuple[str, str]:
        """Extract image to file and return file path.

        The relative path is computed relative to the HTML file's parent directory,
        using a consistent format of {html_stem}_files/{output_filename}.
        """
        image_name = item.get_name()
        image_data = item.get_content()

        # Derive safe filename from basename, preserving extension
        base_filename = Path(image_name).name
        file_extension = Path(base_filename).suffix or ".jpg"
        safe_basename = Path(base_filename).stem or f"image_{self.image_counter + 1}"

        # Check for collision and prepend counter if needed
        output_filename = safe_basename + file_extension
        originally_intended_filename = output_filename  # Track original intent
        output_path: Path = self.output_dir / output_filename  # type: ignore

        collision_count = 0
        while output_path.exists():
            collision_count += 1
            output_filename = f"{safe_basename}_{collision_count}{file_extension}"
            output_path = self.output_dir / output_filename  # type: ignore

        self.image_counter += 1

        # Ensure parent directories exist before writing
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write image with error handling
        try:
            output_path.write_bytes(image_data)
            if collision_count > 0:
                logger.info(
                    "Extracted image %s: originally intended %s, renamed to %s (collision detected). "
                    "Directory: %s",
                    image_name,
                    originally_intended_filename,
                    output_filename,
                    self.output_dir,
                )
            else:
                logger.debug(
                    "Extracted image %s to: %s (directory: %s)",
                    image_name,
                    output_path,
                    self.output_dir,
                )
        except (OSError, IOError) as e:
            logger.warning("Failed to write image %s to %s: %s", image_name, output_path, e)
            raise

        # Compute relative path using hardcoded format: {html_stem}_files/{filename}
        # This decouples the path from absolute filesystem paths and ensures consistency
        assert self.html_root is not None, "html_root must not be None when extracting images"
        assert self.output_dir is not None, "output_dir must not be None when extracting images"

        # Get the HTML stem (filename without extension) from the images directory name
        # html_root is the parent of the HTML file, and output_dir is html_root/{html_stem}_files
        images_folder_name = self.output_dir.name  # Should be "{html_stem}_files"

        # Create POSIX-style path: {html_stem}_files/{output_filename}
        posix_path = f"{images_folder_name}/{output_filename}"

        # URL-encode the path for HTML src attributes to handle spaces and special characters
        # This keeps POSIX separators while encoding each path segment
        encoded_html_path = self._encode_url_path(posix_path)

        self.image_map[image_name] = encoded_html_path

        # Also map by lowercase basename for lookup flexibility using multimap
        basename = Path(image_name).name.lower()
        if basename not in self.basename_map:
            self.basename_map[basename] = []
        self.basename_map[basename].append((image_name, encoded_html_path))

        logger.debug(
            "Extracted image reference: %s (url-encoded path: %s)", image_name, encoded_html_path
        )
        return image_name, encoded_html_path


class EpubConverter:
    """Main EPUB to HTML converter."""

    def __init__(
        self,
        epub_path: Path,
        html_path: Path,
        image_strategy: str = "embed",
        wrap_html: bool = False,
        css: str | None = None,
        show_progress: bool = True,
        allow_unknown_mime: bool = False,
        keep_toc: bool = False,
        keep_cover: bool = False,
        images_dir_name: str = "{stem}_files",
        chunked: bool = False,
    ):
        """
        Initialize the EPUB converter.

        Args:
            epub_path: Path to the input EPUB file
            html_path: Path to the output HTML file
            image_strategy: Strategy for handling images ("embed" or "extract")
            wrap_html: Whether to wrap content in complete HTML structure
            css: Optional CSS to include in the output
            show_progress: Whether to show progress bars for long operations
            allow_unknown_mime: Whether to allow embedding images with unknown MIME types
            keep_toc: Whether to preserve table of contents elements
            keep_cover: Whether to preserve cover page elements
            images_dir_name: Directory name pattern for extracted images (use {stem} for HTML stem)
            chunked: Whether to use chunked/incremental processing for large books
                (processes documents sequentially and replaces image refs per chunk
                before concatenation, useful for memory efficiency with large EPUBs)
        """
        self.epub_path = Path(epub_path)
        self.html_path = Path(html_path)
        self.wrap_html = wrap_html
        self.css = css
        self.show_progress = show_progress
        self.allow_unknown_mime = allow_unknown_mime
        self.keep_toc = keep_toc
        self.keep_cover = keep_cover
        self.images_dir_name = images_dir_name
        self.chunked = chunked
        self._chardet_warning_logged = False

        # Create image handler
        output_dir = None
        if image_strategy == "extract":
            # Create images directory with configurable name
            dir_name = self.images_dir_name.format(stem=self.html_path.stem)
            output_dir = self.html_path.parent / dir_name
            output_dir.mkdir(parents=True, exist_ok=True)

        self.image_handler = ImageHandler(
            image_strategy, output_dir, self.html_path.parent, allow_unknown_mime
        )

        # Counters for tracking extraction decisions
        self.total_docs_processed = 0
        self.total_images_processed = 0
        self.embedded_images_count = 0
        self.extracted_images_count = 0
        self.skipped_images_count = 0
        self.decode_fallbacks_count = 0

    def convert(self) -> None:
        """Convert EPUB to HTML."""
        try:
            logger.info("Reading EPUB: %s", self.epub_path)
            book = epub.read_epub(str(self.epub_path))

            # Extract EPUB title for use in HTML document
            epub_title = None
            try:
                title_list = book.get_metadata("DC", "title")
                if title_list and len(title_list) > 0:
                    # get_metadata returns list of tuples; extract value from first tuple
                    first_title = title_list[0]
                    if isinstance(first_title, tuple) and len(first_title) > 0:
                        epub_title = first_title[0]
                    elif isinstance(first_title, str):
                        epub_title = first_title
            except (AttributeError, IndexError, TypeError):
                pass

            # Process images first
            logger.info("Processing images...")
            self._process_images(book)

            # Extract content
            logger.info("Extracting content...")
            if self.chunked:
                html_content = self._extract_content_chunked(book)
            else:
                html_content = self._extract_content(book)

            # Write output
            logger.info("Writing output to: %s", self.html_path)
            self._write_html(html_content, title=epub_title)

            # Log comprehensive summary
            self._log_conversion_summary()

        except (FileNotFoundError, ValueError) as e:
            logger.error("Invalid input: %s", e)
            raise
        except (IOError, OSError) as e:
            logger.error("File operation failed: %s", e)
            raise
        except Exception as e:
            logger.error("Conversion failed: %s", e, exc_info=True)
            raise

    def _process_images(self, book) -> None:
        """Extract and process all images from the EPUB."""
        # First pass: count images
        items = list(book.get_items())
        image_items = [item for item in items if item.get_type() == ebooklib.ITEM_IMAGE]

        if image_items:
            for item in tqdm(
                image_items,
                desc="Processing images",
                unit="img",
                disable=not self.show_progress,
            ):
                try:
                    self.image_handler.process_image(item)
                    self.total_images_processed += 1
                    # Track embedded vs extracted based on strategy
                    if self.image_handler.strategy == "embed":
                        self.embedded_images_count += 1
                    else:
                        self.extracted_images_count += 1
                except RuntimeError as e:
                    # Handle unknown MIME type when embedding - skip with clear message
                    logger.warning(
                        "Skipping image %s due to unknown MIME type. "
                        "To embed unknown types, use '--strategy extract' instead. Error: %s",
                        item.get_name(),
                        e,
                    )
                    self.skipped_images_count += 1
                except (ValueError, IOError, OSError) as e:
                    logger.warning("Failed to process image %s: %s", item.get_name(), e)
                    self.skipped_images_count += 1
        else:
            logger.info("No images found in EPUB")

    def _extract_content(self, book) -> str:
        """Extract all document content from the EPUB in reading order."""
        html_content = self._extract_by_spine(book)
        if not html_content:
            html_content = self._extract_all_documents(book)

        # Remove cover pages (unless --keep-cover is set)
        if not self.keep_cover:
            logger.info("Removing cover pages...")
            html_content = self._remove_cover(html_content)
        else:
            logger.info("Preserving cover pages (--keep-cover set)")

        # Remove table of contents navigation elements (unless --keep-toc is set)
        if not self.keep_toc:
            logger.info("Removing table of contents...")
            html_content = self._remove_toc(html_content)
        else:
            logger.info("Preserving table of contents (--keep-toc set)")

        # Replace all image references at once after collecting all content
        if self.image_handler.image_map:
            logger.info("Replacing image references...")
            html_content = self._replace_image_references(html_content)

        return html_content

    def _extract_content_chunked(self, book) -> str:
        """
        Extract document content from EPUB using chunked/incremental processing.

        Processes documents sequentially and replaces image references per chunk
        before concatenation. This reduces memory usage for large books by avoiding
        a single large BeautifulSoup parse for the entire document.

        Performance impact: Chunked mode parses HTML multiple times (once per document
        plus once for final assembly), while standard mode parses once. For most books
        (<1000 pages), the difference is negligible. Chunked mode is recommended for
        books >5000 pages or when available memory is limited.
        """
        html_content = ""

        # Try spine-based extraction first
        spine = book.spine if hasattr(book, "spine") else []
        doc_items = self._get_doc_items_from_spine(book, spine) if spine else []

        # Fall back to all documents if spine is empty
        if not doc_items:
            items = list(book.get_items())
            doc_items = [item for item in items if item.get_type() == ebooklib.ITEM_DOCUMENT]

        if not doc_items:
            logger.info("No documents found in EPUB")
            return html_content

        # Process documents sequentially with per-document image replacement
        for item in tqdm(
            doc_items,
            desc="Extracting content (chunked)",
            unit="doc",
            disable=not self.show_progress,
        ):
            try:
                chunk_html = self._decode_document_content(item)
                self.total_docs_processed += 1
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning("Failed to extract document %s: %s", item.get_name(), e)
                continue

            # Replace image references within this chunk before concatenation
            if self.image_handler.image_map:
                chunk_html = self._replace_image_references(chunk_html)

            html_content += chunk_html + "\n"

        # Remove cover and TOC from the full concatenated content
        if not self.keep_cover:
            logger.info("Removing cover pages...")
            html_content = self._remove_cover(html_content)
        else:
            logger.info("Preserving cover pages (--keep-cover set)")

        if not self.keep_toc:
            logger.info("Removing table of contents...")
            html_content = self._remove_toc(html_content)
        else:
            logger.info("Preserving table of contents (--keep-toc set)")

        return html_content

    def _decode_document_content(self, item) -> str:
        """
        Decode document content with UTF-8 fallback to chardet or latin-1.

        Attempts UTF-8 decoding first, then falls back to chardet detection
        or latin-1 if available/configured.

        Args:
            item: The EPUB document item

        Returns:
            Decoded content string

        Raises:
            UnicodeDecodeError: If decoding fails with all methods
            AttributeError: If item doesn't have expected methods
        """
        try:
            content = item.get_content().decode("utf-8")
            return content
        except UnicodeDecodeError:
            logger.warning(
                "UTF-8 decoding failed for %s, attempting alternate encoding",
                item.get_name(),
            )
            try:
                # Try encoding with chardet if available, otherwise fall back to latin-1
                try:
                    import chardet  # pylint: disable=import-outside-toplevel

                    detected = chardet.detect(item.get_content())
                    encoding = detected.get("encoding")
                    confidence = detected.get("confidence", 0)

                    # Fall back to latin-1 if encoding is None or confidence is too low
                    if not encoding or confidence < 0.5:
                        encoding = "latin-1"
                        logger.debug(
                            "Chardet returned None encoding or low confidence (%.2f) for %s, using fallback: %s",
                            confidence,
                            item.get_name(),
                            encoding,
                        )
                    else:
                        logger.debug(
                            "Chardet detected encoding for %s: %s (confidence: %.2f)",
                            item.get_name(),
                            encoding,
                            confidence,
                        )
                except ImportError:
                    encoding = "latin-1"
                    if not self._chardet_warning_logged:
                        logger.info(
                            "chardet not available for encoding detection; using fallback encoding. "
                            "For better accuracy, install it: pip install chardet"
                        )
                        self._chardet_warning_logged = True
                    else:
                        logger.debug("chardet not available, using fallback encoding: %s", encoding)

                content = item.get_content().decode(encoding, errors="replace")
                self.decode_fallbacks_count += 1

                logger.debug(
                    "Successfully decoded %s with encoding: %s",
                    item.get_name(),
                    encoding,
                )
                return content
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning("Failed to extract document %s: %s", item.get_name(), e)
                raise

    def _extract_by_spine(self, book) -> str:
        """Extract documents using the EPUB spine (reading order)."""
        html_content = ""

        spine = book.spine if hasattr(book, "spine") else []

        if not spine:
            return html_content

        doc_items = self._get_doc_items_from_spine(book, spine)

        if not doc_items:
            logger.info("No documents found in EPUB spine")
            return html_content

        for item in tqdm(
            doc_items,
            desc="Extracting content",
            unit="doc",
            disable=not self.show_progress,
        ):
            try:
                content = self._decode_document_content(item)
                html_content += content + "\n"
                self.total_docs_processed += 1
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning("Failed to extract document %s: %s", item.get_name(), e)

        return html_content

    def _get_doc_items_from_spine(self, book, spine):
        """Helper to collect document items from the spine."""
        doc_items = []
        for spine_item in spine:
            item_id = spine_item[0] if isinstance(spine_item, tuple) else spine_item
            try:
                item = book.get_item_with_id(item_id)
                if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                    doc_items.append(item)
            except (KeyError, AttributeError):
                pass
        return doc_items

    def _extract_all_documents(self, book) -> str:
        """Fallback: extract all documents without spine order."""
        logger.warning("No spine found in EPUB, falling back to unordered extraction")
        html_content = ""
        items = list(book.get_items())
        doc_items = [item for item in items if item.get_type() == ebooklib.ITEM_DOCUMENT]

        if not doc_items:
            logger.info("No documents found in EPUB")
            return html_content

        for item in tqdm(
            doc_items,
            desc="Extracting content",
            unit="doc",
            disable=not self.show_progress,
        ):
            try:
                content = self._decode_document_content(item)
                html_content += content + "\n"
                self.total_docs_processed += 1
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning("Failed to extract document %s: %s", item.get_name(), e)

        return html_content

    def _remove_toc(self, content: str) -> str:
        """Remove table of contents navigation elements from HTML using DOM traversal.

        Finds and removes:
        - nav elements with epub:type="toc"
        - nav/div/section elements with class containing 'toc' as a token
        - Common EPUB TOC markers

        Returns consistent HTML output with nodes removed.
        """
        from bs4 import BeautifulSoup  # pylint: disable=import-outside-toplevel

        soup = BeautifulSoup(content, "html.parser")
        removed_count = 0

        # Pattern 1: Find nav elements with epub:type="toc"
        for nav in soup.find_all("nav"):
            epub_type = nav.get("epub:type")
            if epub_type:
                # Handle both string and list (BeautifulSoup may return list for attributes)
                epub_type_str = str(epub_type) if epub_type else ""
                # Check if 'toc' is present as a token in epub:type (handles "toc", "toc other", etc.)
                if any(token == "toc" for token in epub_type_str.split()):
                    nav.decompose()
                    removed_count += 1

        # Pattern 2: Find elements with class containing 'toc' as a whole token
        for tag in soup.find_all(["nav", "div", "section", "article"]):
            class_attr = tag.get("class")
            if class_attr:
                # BeautifulSoup parses class as a list
                classes = class_attr if isinstance(class_attr, list) else str(class_attr).split()
                if any(cls.lower() == "toc" for cls in classes):
                    tag.decompose()
                    removed_count += 1

        if removed_count > 0:
            logger.info("Removed %d TOC elements", removed_count)

        return str(soup)

    def _remove_cover(self, content: str) -> str:
        """Remove cover page sections from HTML using DOM traversal.

        Finds and removes:
        - Elements with epub:type="cover"
        - Elements with class containing 'cover' as a token
        - Common EPUB cover markers (div/section/article tags)

        Returns consistent HTML output with nodes removed.
        """
        from bs4 import BeautifulSoup  # pylint: disable=import-outside-toplevel

        soup = BeautifulSoup(content, "html.parser")
        removed_count = 0

        # Pattern 1: Find elements with epub:type="cover"
        for tag in soup.find_all(["section", "div", "article"]):
            epub_type = tag.get("epub:type")
            if epub_type:
                # Handle both string and list (BeautifulSoup may return list for attributes)
                epub_type_str = str(epub_type) if epub_type else ""
                # Check if 'cover' is present as a token in epub:type (handles "cover", "cover other", etc.)
                if any(token == "cover" for token in epub_type_str.split()):
                    tag.decompose()
                    removed_count += 1

        # Pattern 2: Find elements with class containing 'cover' as a whole token
        for tag in soup.find_all(["div", "section", "article"]):
            class_attr = tag.get("class")
            if class_attr:
                # BeautifulSoup parses class as a list
                classes = class_attr if isinstance(class_attr, list) else str(class_attr).split()
                if any(cls.lower() == "cover" for cls in classes):
                    tag.decompose()
                    removed_count += 1

        if removed_count > 0:
            logger.info("Removed %d cover elements", removed_count)

        return str(soup)

    def _parse_and_replace_srcset(self, srcset_str: str) -> str:
        """
        Parse srcset attribute and replace URLs while preserving descriptors.

        Follows the spec: split on commas not inside parentheses, then for each
        candidate split on whitespace into URL and descriptors, preserving order.
        Only replaces the URL token, leaving descriptors untouched.

        Args:
            srcset_str: The srcset attribute value

        Returns:
            Processed srcset with replaced URLs and preserved descriptors
        """
        # Split on commas not inside parentheses
        candidates = self._split_srcset_candidates(srcset_str)
        result_parts = []

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue

            # Split candidate into URL and descriptors
            # URL is everything up to first whitespace, descriptors are the rest
            tokens = candidate.split(None, 1)  # Split on first whitespace
            if not tokens:
                result_parts.append(candidate)
                continue

            url = tokens[0].strip()
            descriptor = tokens[1] if len(tokens) > 1 else ""

            # Attempt replacement
            replacement = self._get_image_replacement(url)
            if replacement:
                # Replace URL, preserve descriptor
                if descriptor:
                    result_parts.append(f"{replacement} {descriptor}")
                else:
                    result_parts.append(replacement)
            else:
                # Original URL preserved, log warning
                if descriptor:
                    result_parts.append(f"{url} {descriptor}")
                else:
                    result_parts.append(url)
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unresolved image reference in srcset: %s",
                        url,
                    )

        return ", ".join(result_parts)

    def _split_srcset_candidates(self, srcset_str: str) -> list[str]:
        """
        Split srcset string on commas, respecting parentheses (data URLs, etc).

        Args:
            srcset_str: The srcset attribute value

        Returns:
            List of candidates split on top-level commas
        """
        candidates = []
        current = []
        paren_depth = 0

        for char in srcset_str:
            if char == "(":
                paren_depth += 1
                current.append(char)
            elif char == ")":
                paren_depth -= 1
                current.append(char)
            elif char == "," and paren_depth == 0:
                candidates.append("".join(current))
                current = []
            else:
                current.append(char)

        if current:
            candidates.append("".join(current))

        return candidates

    def _replace_image_references(self, content: str) -> str:
        """Replace image references with embedded or extracted versions using BeautifulSoup.

        Uses basename mapping when available for flexible reference matching.
        Only replaces when a unique basename mapping exists; skips with warning otherwise.
        """
        if not self.image_handler.image_map:
            return content

        from bs4 import BeautifulSoup  # pylint: disable=import-outside-toplevel

        soup = BeautifulSoup(content, "html.parser")

        # Define image-bearing tags and their source attributes
        image_tag_specs = [
            ("img", ["src"]),
            ("image", ["href", "xlink:href"]),
            ("source", ["srcset", "src"]),
        ]

        unresolved_count = 0

        # Process each tag and look up images by basename
        for tag_name, attributes in image_tag_specs:
            tags = soup.find_all(tag_name)
            for tag in tags:
                for attr in attributes:
                    attr_value = tag.get(attr)
                    if not attr_value:
                        continue

                    # Convert attribute value to string (handles BeautifulSoup's _AttributeValue types)
                    attr_value_str = str(attr_value)

                    # For srcset attribute, process with spec-compliant parser
                    if attr == "srcset":
                        processed_srcset = self._parse_and_replace_srcset(attr_value_str)
                        tag[attr] = processed_srcset
                    else:
                        # For src/href attributes, try to find and replace using basename mapping
                        replacement = self._get_image_replacement(attr_value_str)
                        if replacement:
                            tag[attr] = replacement
                        else:
                            unresolved_count += 1
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "Unresolved image reference: %s (tag: %s, attr: %s)",
                                    attr_value_str,
                                    tag_name,
                                    attr,
                                )

        if unresolved_count > 0:
            logger.info(
                "Completed image replacement with %d unresolved references (original URLs preserved)",
                unresolved_count,
            )

        return str(soup)

    def _get_image_replacement(self, url: str) -> str | None:
        """
        Look up an image URL and return the replacement URL/path.

        Implementation order:
        1. Exact match against image_map for the full original path
        2. Relative path resolution (if document base path is known)
        3. Unambiguous basename lookup (only if single entry exists)

        Returns None for ambiguous basenames or no matches.

        Args:
            url: The URL/path to look up

        Returns:
            The replacement URL/path, or None if no unique mapping exists
        """
        # Extract base URL part (without query string or fragment)
        base_url = url.split("?")[0].split("#")[0]

        # Step 1: Exact match in image_map
        if base_url in self.image_handler.image_map:
            return self.image_handler.image_map[base_url]

        # Step 2: Try to resolve relative paths
        # Extract basename from URL for matching
        url_basename = Path(base_url).name.lower()
        if not url_basename:
            return None

        # Check if URL contains a filename that matches an original exactly
        for original_name, image_url in self.image_handler.image_map.items():
            original_basename = Path(original_name).name
            if url_basename == original_basename.lower():
                return image_url

        # Step 3: Unambiguous basename lookup
        if url_basename in self.image_handler.basename_map:
            candidates = self.image_handler.basename_map[url_basename]
            if len(candidates) == 1:
                # Unique match found
                return candidates[0][1]
            if len(candidates) > 1:
                # Ambiguous: multiple images with same basename
                logger.warning(
                    "Ambiguous image reference: '%s' matches multiple files with basename '%s' "
                    "from different folders (%s). Skipping replacement to avoid incorrect substitution.",
                    url,
                    url_basename,
                    ", ".join(orig for orig, _ in candidates),
                )
                return None

        # No match found
        return None

    def _write_html(self, content: str, title: str | None = None) -> None:
        """Write HTML content to output file."""
        self.html_path.parent.mkdir(parents=True, exist_ok=True)

        if self.wrap_html:
            content = self._wrap_in_html_structure(content, title=title)

        with open(self.html_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _log_conversion_summary(self) -> None:
        """Log a comprehensive summary of extraction decisions and processing statistics."""
        images_dir = None
        if self.image_handler.strategy == "extract":
            images_dir = str(self.image_handler.output_dir)

        summary_parts = [
            f"docs_processed={self.total_docs_processed}",
            f"images_processed={self.total_images_processed}",
            f"embedded={self.embedded_images_count}",
            f"extracted={self.extracted_images_count}",
            f"skipped_images={self.skipped_images_count}",
            f"output={self.html_path}",
        ]

        if images_dir:
            summary_parts.append(f"images_dir={images_dir}")

        if self.decode_fallbacks_count > 0:
            summary_parts.append(f"encoding_fallbacks={self.decode_fallbacks_count}")
            logger.info(
                "Note: %d document(s) required encoding fallback detection. "
                "For better accuracy, consider installing chardet: pip install chardet",
                self.decode_fallbacks_count,
            )

        summary = " | ".join(summary_parts)
        logger.info("Conversion complete! Summary: %s", summary)

    def _wrap_in_html_structure(self, content: str, title: str | None = None) -> str:
        """Wrap content in a complete HTML structure."""
        import textwrap  # pylint: disable=import-outside-toplevel

        # Use provided title or fall back to default
        page_title = title if title else "EPUB Document"

        css_block = ""
        if self.css:
            css_block = f"<style>\n{self.css}\n</style>"

        default_css = textwrap.dedent("""
        body {
            font-family: Georgia, serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }
        img {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 20px 0;
        }
        h1, h2, h3, h4, h5, h6 {
            margin-top: 1.5em;
            margin-bottom: 0.5em;
        }
        p {
            text-align: justify;
        }
        """).strip()

        if not self.css:
            css_block = f"<style>\n{default_css}\n</style>"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    {css_block}
</head>
<body>
    {content}
</body>
</html>
"""
        return html


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Convert an EPUB file to HTML format with flexible image handling."
    )

    parser.add_argument("epub_path", type=str, help="Path to the input EPUB file")

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="output.html",
        help="Path to output HTML file (relative paths are resolved from the current working directory; default: output.html)",
    )

    parser.add_argument(
        "-s",
        "--strategy",
        choices=["embed", "extract"],
        default="embed",
        help="Image handling: 'embed' for base64 or 'extract' for separate files (default: embed)",
    )

    parser.add_argument(
        "-w",
        "--wrap",
        action="store_true",
        help="Wrap content in complete HTML structure with default styling",
    )

    parser.add_argument(
        "-c",
        "--css",
        type=str,
        help="Path to a CSS file whose contents will be inlined into a <style> tag; implies --wrap",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG level) for troubleshooting",
    )

    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars for long-running operations",
    )

    parser.add_argument(
        "--allow-unknown-mime",
        action="store_true",
        help="Allow embedding images with unknown MIME types; only relevant with --strategy embed. When enabled and media type cannot be determined, images will be skipped (use --strategy extract instead)",
    )

    parser.add_argument(
        "--keep-toc",
        action="store_true",
        help="Preserve table of contents elements instead of removing them (default: remove TOC)",
    )

    parser.add_argument(
        "--keep-cover",
        action="store_true",
        help="Preserve cover page elements instead of removing them (default: remove cover)",
    )

    parser.add_argument(
        "--images-dir-name",
        type=str,
        default="{stem}_files",
        help="Directory name pattern for extracted images when using --strategy extract. Use {stem} as placeholder for HTML filename stem (default: {stem}_files)",
    )

    parser.add_argument(
        "--force-progress",
        action="store_true",
        help="Force progress bars even when stderr is not a TTY; useful for CI logs (respects --no-progress if set)",
    )

    parser.add_argument(
        "--chunked",
        action="store_true",
        help="Use chunked/incremental processing for large books: processes documents sequentially "
        "and replaces image references per chunk before concatenation. Reduces memory usage for very large EPUBs (>5000 pages). "
        "May be slightly slower due to multiple HTML parses, but negligible difference for most books.",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Set logging level (default: DEBUG if -v/--verbose, else INFO)",
    )

    parser.add_argument(
        "--log-format",
        type=str,
        default="%(asctime)s - %(levelname)s - %(message)s",
        help="Set logging format (default: '%(asctime)s - %(levelname)s - %(message)s')",
    )

    args = parser.parse_args()

    # Configure logging dynamically based on verbosity and log-level
    if args.log_level:
        # Explicit --log-level takes precedence
        log_level = getattr(logging, args.log_level)
    elif args.verbose:
        # -v/--verbose is a shorthand for DEBUG
        log_level = logging.DEBUG
    else:
        # Default to INFO
        log_level = logging.INFO

    logging.basicConfig(level=log_level, format=args.log_format)

    # Read CSS if provided
    css_content = None
    if args.css:
        css_path = Path(args.css)
        if not css_path.exists():
            logger.error("CSS file not found: %s", css_path)
            sys.exit(1)
        css_content = css_path.read_text(encoding="utf-8")

    wrap_html = args.wrap or (args.css is not None)

    # Validate EPUB file exists
    epub_path = Path(args.epub_path)
    if not epub_path.exists():
        logger.error("EPUB file not found: %s", epub_path)
        sys.exit(1)

    # Resolve output path to absolute
    output_path = Path(args.output).resolve()
    logger.info("Resolved output path: %s", output_path)

    # Validate --images-dir-name doesn't equal HTML filename to avoid collisions
    images_dir_name = args.images_dir_name
    final_images_dir_name = images_dir_name.format(stem=output_path.stem)
    if final_images_dir_name == output_path.name:
        logger.error(
            "Images directory name (%s) cannot equal HTML filename (%s); this would cause a collision.",
            final_images_dir_name,
            output_path.name,
        )
        sys.exit(1)

    # Determine show_progress based on TTY and --force-progress
    show_progress = True
    if args.no_progress:
        show_progress = False
    elif args.force_progress:
        show_progress = True
    else:
        show_progress = sys.stderr.isatty()

    try:
        converter = EpubConverter(
            epub_path=args.epub_path,
            html_path=output_path,
            image_strategy=args.strategy,
            wrap_html=wrap_html,
            css=css_content,
            show_progress=show_progress,
            allow_unknown_mime=args.allow_unknown_mime,
            keep_toc=args.keep_toc,
            keep_cover=args.keep_cover,
            images_dir_name=images_dir_name,
            chunked=args.chunked,
        )
        converter.convert()

        # Log resolved paths after conversion
        if args.strategy == "extract":
            final_dir_name = args.images_dir_name.format(stem=output_path.stem)
            images_dir = output_path.parent / final_dir_name
            logger.info("Images extracted to: %s", images_dir)
    except (ValueError, OSError, IOError) as e:
        logger.error("Failed to convert EPUB: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
