"""Convert an EPUB publication into one navigable HTML document.

The converter preserves EPUB spine order where available, namespaces document IDs,
and rewrites internal links so that navigation still works after separate XHTML
files are merged. Images can be embedded for a self-contained result or extracted
beside the HTML file when output size matters more than portability.
"""

import argparse
import base64
import html as html_module
import logging
import os
import posixpath
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from urllib.parse import quote, unquote, urlsplit

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from rich.console import Console, Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)
console = Console(stderr=True)


class ArchiveLimitError(ValueError):
    """Raised when an EPUB archive violates the configured safety policy."""


class OutputError(OSError):
    """Raised when staged output cannot be committed safely."""


@dataclass(frozen=True)
class ArchiveLimits:
    """Resource limits applied before EbookLib opens an EPUB archive."""

    max_entries: int = 10_000
    max_compressed_bytes: int = 256 * 1024 * 1024
    max_expanded_bytes: int = 1 * 1024 * 1024 * 1024
    max_entry_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 1_000.0
    max_documents: int = 5_000
    max_images: int = 10_000
    max_output_bytes: int = 1 * 1024 * 1024 * 1024

    def validate(self) -> None:
        """Reject invalid policy values before any expensive conversion work."""
        for name in (
            "max_entries",
            "max_compressed_bytes",
            "max_expanded_bytes",
            "max_entry_bytes",
            "max_documents",
            "max_images",
            "max_output_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be greater than zero")


def preflight_archive(epub_path: Path, limits: ArchiveLimits) -> None:
    """Validate ZIP structure and resource costs before EbookLib parses an EPUB."""
    limits.validate()
    try:
        with zipfile.ZipFile(epub_path) as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_entries:
                raise ArchiveLimitError(
                    f"Archive contains {len(entries):,} entries; the limit is "
                    f"{limits.max_entries:,}."
                )

            names: set[str] = set()
            compressed_bytes = 0
            expanded_bytes = 0
            for info in entries:
                raw_name = info.filename
                normalized_name = raw_name.replace("\\", "/")
                path_parts = normalized_name.split("/")
                if (
                    not normalized_name
                    or normalized_name.startswith("/")
                    or re.match(r"^[A-Za-z]:", normalized_name)
                    or ".." in path_parts
                    or "\x00" in normalized_name
                ):
                    raise ArchiveLimitError(f"Archive contains unsafe member name: {raw_name!r}.")

                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ArchiveLimitError(
                        f"Archive contains unsupported symbolic link member: {raw_name!r}."
                    )

                if raw_name in names:
                    raise ArchiveLimitError(f"Archive contains duplicate member: {raw_name!r}.")
                names.add(raw_name)

                compressed_bytes += info.compress_size
                expanded_bytes += info.file_size
                if info.file_size > limits.max_entry_bytes:
                    raise ArchiveLimitError(
                        f"Archive member {raw_name!r} expands to {info.file_size:,} bytes; "
                        f"the per-entry limit is {limits.max_entry_bytes:,}."
                    )
                if info.compress_size == 0:
                    if info.file_size > 0:
                        raise ArchiveLimitError(
                            f"Archive member {raw_name!r} has an invalid compression ratio."
                        )
                elif info.file_size / info.compress_size > limits.max_compression_ratio:
                    raise ArchiveLimitError(
                        f"Archive member {raw_name!r} exceeds the compression-ratio limit "
                        f"of {limits.max_compression_ratio:g}."
                    )

            if compressed_bytes > limits.max_compressed_bytes:
                raise ArchiveLimitError(
                    f"Archive compressed size is {compressed_bytes:,} bytes; the limit is "
                    f"{limits.max_compressed_bytes:,}."
                )
            if expanded_bytes > limits.max_expanded_bytes:
                raise ArchiveLimitError(
                    f"Archive expanded size is {expanded_bytes:,} bytes; the limit is "
                    f"{limits.max_expanded_bytes:,}."
                )

            required_members = {"mimetype", "META-INF/container.xml"}
            missing_members = required_members - names
            if missing_members:
                missing = ", ".join(sorted(missing_members))
                raise ValueError(f"EPUB archive is missing required member(s): {missing}.")
    except zipfile.BadZipFile as error:
        raise ValueError(f"Input is not a valid ZIP/EPUB archive: {error}") from error


class CompactRichHandler(RichHandler):
    """Render color-coded log levels without Rich's default fixed-width padding."""

    def get_level_text(self, record: logging.LogRecord) -> Text:
        """Return the styled level name at its natural width."""
        return Text.styled(record.levelname, f"logging.level.{record.levelname.lower()}")


class RichArgumentParser(argparse.ArgumentParser):
    """Render command help and argument errors using Rich."""

    def print_help(self, file: object | None = None) -> None:
        del file
        console.print(
            Panel.fit(
                Text("EPUB → HTML", style="bold bright_cyan"),
                border_style="bright_cyan",
            )
        )
        usage = Text.from_ansi(self.format_usage().strip())
        console.print("[bold]Usage[/]")
        console.print(usage)
        if self.description:
            console.print(f"\n[dim]{self.description}[/]")

        options = Table(show_header=False, box=None, padding=(0, 2), expand=False)
        options.add_column("Option", style="bold cyan", no_wrap=True)
        options.add_column("Description")
        for action in self._actions:
            if action.help is argparse.SUPPRESS:
                continue
            option_names = ", ".join(action.option_strings)
            if not option_names:
                option_names = str(action.metavar or action.dest.upper())
            elif action.metavar and action.nargs != 0:
                option_names = f"{option_names} {action.metavar}"
            help_text = Text(action.help or "")
            if (
                action.default is not None
                and action.default is not argparse.SUPPRESS
                and action.option_strings
            ):
                help_text.append(f" (default: {action.default})", style="bright_white")
            options.add_row(option_names, help_text)

        console.print("\n[bold]Options[/]")
        console.print(options)

    def error(self, message: str) -> NoReturn:
        console.print(Panel(message, title="[bold red]Invalid command[/]", border_style="red"))
        console.print(Text.from_ansi(self.format_usage().strip()), style="dim")
        raise SystemExit(2)


class ImageHandler:
    """Create stable HTML image references for one conversion.

    Both mappings are retained because EPUBs commonly use document-relative paths,
    while some producers use only a filename. Basename fallback is deliberately
    limited to unique names so similarly named assets never silently point to the
    wrong image.
    """

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
        # Keep full paths for exact EPUB-relative resolution and basenames only as
        # a guarded fallback for EPUBs that omit their asset directory.
        self.image_map: dict[str, str] = {}
        self.basename_map: dict[str, list[tuple[str, str]]] = {}
        self.image_counter = 0

        if strategy == "extract" and not output_dir:
            raise ValueError("output_dir required when using 'extract' strategy")
        if strategy == "extract" and not html_root:
            raise ValueError(
                "html_root required when using 'extract' strategy for relative path computation"
            )

    def process_image(self, item: epub.EpubItem) -> tuple[str, str]:
        """Convert one EPUB image according to the configured output strategy.

        Returns the original EPUB resource name with its replacement HTML URL.
        In extract mode this writes a file under ``output_dir``; in embed mode the
        replacement is a data URL and no additional file is created.

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
        segments = posix_path.split("/")
        encoded_segments = [quote(segment, safe="") for segment in segments]
        return "/".join(encoded_segments)

    def _embed_image(self, item: epub.EpubItem) -> tuple[str, str]:
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

        media_type = item.media_type
        if not media_type:
            # The manifest is authoritative when present; filenames are a useful
            # fallback for EPUBs with incomplete or nonstandard manifests.
            media_type = mimetypes.guess_type(image_name)[0]

        if not media_type:
            # ``mimetypes`` varies with the host OS, so provide the common web
            # formats explicitly for predictable output across platforms.
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

        if not media_type:
            if not self.allow_unknown_mime:
                error_msg = (
                    f"Cannot determine media type for image '{image_name}'. "
                    f"Use '--allow-unknown-mime' to skip type detection, "
                    f"or use '--strategy extract' to save images as files instead."
                )
                raise ValueError(error_msg)
            error_msg = (
                f"Unknown media type for image '{image_name}'. "
                f"Embedding with unknown MIME types is not recommended. "
                f"Use '--strategy extract' to save images as separate files instead."
            )
            logger.warning(error_msg)
            raise RuntimeError(error_msg)

        image_url = f"data:{media_type};base64,{base64_data}"

        self.image_map[image_name] = image_url

        # Multiple source images can share a basename; retain all candidates so
        # lookup can reject an ambiguous reference instead of guessing.
        basename = Path(image_name).name.lower()
        if basename not in self.basename_map:
            self.basename_map[basename] = []
        self.basename_map[basename].append((image_name, image_url))

        logger.debug("Embedded image: %s (media type: %s)", image_name, media_type)
        return image_name, image_url

    def _extract_image(self, item: epub.EpubItem) -> tuple[str, str]:
        """Extract an image and return a browser-safe, HTML-relative reference.

        Filename collisions are resolved instead of overwriting existing files. This
        matters when an EPUB itself contains repeated basenames or when converting
        again into an existing output directory.
        """
        assert self.output_dir is not None, "output_dir must not be None when extracting images"

        image_name = item.get_name()
        image_data = item.get_content()

        base_filename = Path(image_name).name
        file_extension = Path(base_filename).suffix or ".jpg"
        safe_basename = Path(base_filename).stem or f"image_{self.image_counter + 1}"

        output_filename = safe_basename + file_extension
        originally_intended_filename = output_filename
        output_path = self.output_dir / output_filename

        # EPUBs may reuse a basename in different internal folders, and a previous
        # conversion may already occupy the destination. Never overwrite either.
        collision_count = 0
        while output_path.exists():
            collision_count += 1
            output_filename = f"{safe_basename}_{collision_count}{file_extension}"
            output_path = self.output_dir / output_filename

        self.image_counter += 1

        output_path.parent.mkdir(parents=True, exist_ok=True)

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

        assert self.html_root is not None, "html_root must not be None when extracting images"

        # References are relative to the HTML file, not to the EPUB's original
        # internal path, so extracted output remains movable as one directory.
        images_folder_name = self.output_dir.name

        # HTML URLs always use forward slashes, even when conversion runs on Windows.
        posix_path = f"{images_folder_name}/{output_filename}"

        encoded_html_path = self._encode_url_path(posix_path)

        self.image_map[image_name] = encoded_html_path

        basename = Path(image_name).name.lower()
        if basename not in self.basename_map:
            self.basename_map[basename] = []
        self.basename_map[basename].append((image_name, encoded_html_path))

        logger.debug(
            "Extracted image reference: %s (url-encoded path: %s)", image_name, encoded_html_path
        )
        return image_name, encoded_html_path


class EpubConverter:
    """Coordinate EPUB resource processing and merged-document generation.

    A single converter instance owns all source-to-output mappings and statistics.
    Keeping that state per conversion prevents links and images from one run from
    affecting another run in the same Python process.
    """

    def __init__(
        self,
        epub_path: Path,
        html_path: Path,
        image_strategy: str = "embed",
        wrap_html: bool = False,
        css: str | None = None,
        show_progress: bool = True,
        allow_unknown_mime: bool = False,
        remove_toc: bool = False,
        remove_cover: bool = False,
        images_dir_name: str = "{stem}_files",
        chunked: bool = False,
        safe_html: bool = False,
        force: bool = False,
        archive_limits: ArchiveLimits | None = None,
        ui_console: Console = console,
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
            remove_toc: Whether to remove table of contents elements
            remove_cover: Whether to remove cover page elements
            images_dir_name: Directory name pattern for extracted images (use {stem} for HTML stem)
            chunked: Whether to use chunked/incremental processing for large books
                (processes documents sequentially and replaces image refs per chunk
                before concatenation, useful for memory efficiency with large EPUBs)
            safe_html: Remove active and unsafe markup before emitting HTML when enabled
            force: Allow replacing existing output paths
            archive_limits: Resource limits for archive and generated output
        """
        self.epub_path = Path(epub_path)
        self.html_path = Path(html_path)
        self.wrap_html = wrap_html
        self.css = css
        self.show_progress = show_progress
        self.allow_unknown_mime = allow_unknown_mime
        self.remove_toc = remove_toc
        self.remove_cover = remove_cover
        self.images_dir_name = images_dir_name
        self.chunked = chunked
        self.safe_html = safe_html
        self.force = force
        self.archive_limits = archive_limits or ArchiveLimits()
        self.ui_console = ui_console
        self._chardet_warning_logged = False
        self._final_html_path = self.html_path
        self._staging_root: Path | None = None
        self._staged_image_dir: Path | None = None

        output_dir = None
        if image_strategy == "extract":
            self._validate_images_dir_name(images_dir_name)
            dir_name = self.images_dir_name.format(stem=self.html_path.stem)
            output_dir = self.html_path.parent / dir_name

        self.image_handler = ImageHandler(
            image_strategy, output_dir, self.html_path.parent, allow_unknown_mime
        )

        self.total_docs_processed = 0
        self.total_images_processed = 0
        self.embedded_images_count = 0
        self.extracted_images_count = 0
        self.skipped_images_count = 0
        self.decode_fallbacks_count = 0
        # These maps are rebuilt for every conversion because generated anchors
        # depend on the current book's document paths and IDs.
        self.document_anchors: dict[str, str] = {}
        self.document_id_maps: dict[str, dict[str, str]] = {}

    @staticmethod
    def _validate_images_dir_name(pattern: str) -> None:
        """Ensure extracted assets remain a single directory below the output."""
        if (
            not pattern
            or "{" in pattern.replace("{stem}", "")
            or "}" in pattern.replace("{stem}", "")
        ):
            raise ValueError("images_dir_name may use only the {stem} placeholder")
        expanded = pattern.format(stem="output")
        if (
            not expanded
            or expanded in {".", ".."}
            or Path(expanded).name != expanded
            or Path(expanded).is_absolute()
        ):
            raise ValueError("images_dir_name must be a safe directory basename")

    def convert(self) -> None:
        """Convert the configured EPUB and write its HTML output.

        Reads metadata before processing resources so a wrapped document can use the
        EPUB title. Exceptions are logged with an operation-specific message and
        re-raised for the CLI to present a concise failure panel and non-zero exit.
        """
        self.archive_limits.validate()
        if not self.epub_path.is_file():
            raise FileNotFoundError(
                f"EPUB file not found or is not a regular file: {self.epub_path}"
            )
        if self.html_path.exists() and not self.force:
            raise OutputError(
                f"Output already exists: {self.html_path}. Use --force to replace it."
            )
        if self.image_handler.strategy == "extract":
            image_dir_name = self.images_dir_name.format(stem=self.html_path.stem)
            final_image_dir = self.html_path.parent / image_dir_name
            if final_image_dir.exists() and not self.force:
                raise OutputError(
                    f"Extracted-image directory already exists: {final_image_dir}. "
                    "Use --force to replace it."
                )

        preflight_archive(self.epub_path, self.archive_limits)
        self.html_path.parent.mkdir(parents=True, exist_ok=True)
        self._staging_root = Path(
            tempfile.mkdtemp(prefix=f".{self.html_path.stem}-staging-", dir=self.html_path.parent)
        )
        staged_html_path = self._staging_root / self.html_path.name
        self.html_path = staged_html_path
        if self.image_handler.strategy == "extract":
            dir_name = self.images_dir_name.format(stem=self._final_html_path.stem)
            self._staged_image_dir = self._staging_root / dir_name
            self.image_handler.output_dir = self._staged_image_dir

        try:
            logger.info("Reading EPUB: %s", self.epub_path)
            book = epub.read_epub(str(self.epub_path))

            manifest_items = list(book.get_items())
            document_count = sum(
                item.get_type() == ebooklib.ITEM_DOCUMENT for item in manifest_items
            )
            image_count = sum(
                item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER)
                for item in manifest_items
            )
            if document_count > self.archive_limits.max_documents:
                raise ArchiveLimitError(
                    f"EPUB contains {document_count:,} documents; the limit is "
                    f"{self.archive_limits.max_documents:,}."
                )
            if image_count > self.archive_limits.max_images:
                raise ArchiveLimitError(
                    f"EPUB contains {image_count:,} images; the limit is "
                    f"{self.archive_limits.max_images:,}."
                )

            epub_title = None
            try:
                # ebooklib metadata differs between EPUB versions and producers:
                # accept its common tuple form as well as a plain string.
                title_list = book.get_metadata("DC", "title")
                if title_list and len(title_list) > 0:
                    first_title = title_list[0]
                    if isinstance(first_title, tuple) and len(first_title) > 0:
                        epub_title = first_title[0]
                    elif isinstance(first_title, str):
                        epub_title = first_title
            except (AttributeError, IndexError, TypeError):
                pass

            logger.info("Processing images...")
            self._process_images(book)

            logger.info("Extracting content...")
            if self.chunked:
                html_content = self._extract_content_chunked(book)
            else:
                html_content = self._extract_content(book)

            logger.info("Writing output to: %s", self.html_path)
            self._write_html(html_content, title=epub_title)

            output_size = self._staged_output_size()
            if output_size > self.archive_limits.max_output_bytes:
                raise ArchiveLimitError(
                    f"Generated output is {output_size:,} bytes; the output limit is "
                    f"{self.archive_limits.max_output_bytes:,}."
                )

            self._commit_staged_output()

            self._log_conversion_summary()

        except (FileNotFoundError, ValueError) as e:
            logger.log(logging.ERROR, "Invalid input: %s", e)
            raise
        except (IOError, OSError) as e:
            logger.log(logging.ERROR, "File operation failed: %s", e)
            raise
        except Exception as e:
            logger.log(logging.ERROR, "Conversion failed: %s", e)
            raise
        finally:
            self._cleanup_staging()

    def _commit_staged_output(self) -> None:
        """Atomically replace the requested output and extracted asset directory."""
        if self._staging_root is None:
            raise OutputError("Output staging was not initialized")

        final_html = self._final_html_path
        final_images = None
        if self._staged_image_dir is not None:
            final_images = final_html.parent / self._staged_image_dir.name

        backup_root = Path(
            tempfile.mkdtemp(prefix=f".{final_html.stem}-backup-", dir=final_html.parent)
        )
        backed_up: list[tuple[Path, Path]] = []
        committed: list[Path] = []
        try:
            for target in (final_html, final_images):
                if target is None or not target.exists():
                    continue
                if not self.force:
                    raise OutputError(
                        f"Output already exists: {target}. Use --force to replace it."
                    )
                backup = backup_root / target.name
                os.replace(target, backup)
                backed_up.append((target, backup))

            os.replace(self.html_path, final_html)
            committed.append(final_html)
            if self._staged_image_dir is not None and self._staged_image_dir.exists():
                if final_images is None:
                    raise OutputError("Image staging was configured without a final image path")
                os.replace(self._staged_image_dir, final_images)
                committed.append(final_images)
            self.html_path = final_html
            self.image_handler.output_dir = final_images
        except OSError as error:
            for target in reversed(committed):
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
            for target, backup in reversed(backed_up):
                if backup.exists():
                    os.replace(backup, target)
            raise OutputError(f"Could not commit converted output: {error}") from error
        finally:
            shutil.rmtree(backup_root, ignore_errors=True)

    def _staged_output_size(self) -> int:
        """Return the total byte size of all files waiting to be committed."""
        if self._staging_root is None:
            raise OutputError("Output staging was not initialized")
        return sum(path.stat().st_size for path in self._staging_root.rglob("*") if path.is_file())

    def _cleanup_staging(self) -> None:
        """Remove private staging files after success or failure."""
        if self._staging_root is not None:
            shutil.rmtree(self._staging_root, ignore_errors=True)
        self.html_path = self._final_html_path

    def _track_items(
        self, items: list[epub.EpubItem], description: str, unit: str
    ) -> Iterable[epub.EpubItem]:
        """Yield items with an optional Rich progress display."""
        if not self.show_progress:
            yield from items
            return

        with Progress(
            SpinnerColumn(style="bright_cyan"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.ui_console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"{description} ({unit})", total=len(items))
            for item in items:
                yield item
                # Advance after yielding so the display only counts an item once
                # its caller has finished processing it.
                progress.advance(task)

    def _process_images(self, book: epub.EpubBook) -> None:
        """Extract and process all image and cover-image resources from the EPUB."""
        items = list(book.get_items())
        image_item_types = (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER)
        image_items = [item for item in items if item.get_type() in image_item_types]

        if image_items:
            for item in self._track_items(image_items, "Processing images", "img"):
                try:
                    self.image_handler.process_image(item)
                    self.total_images_processed += 1
                    if self.image_handler.strategy == "embed":
                        self.embedded_images_count += 1
                    else:
                        self.extracted_images_count += 1
                except RuntimeError as e:
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

    def _extract_content(self, book: epub.EpubBook) -> str:
        """Extract all document content from the EPUB in reading order."""
        doc_items = self._get_document_items(book)
        return self._assemble_documents(doc_items, "Extracting content")

    def _extract_content_chunked(self, book: epub.EpubBook) -> str:
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
        doc_items = self._get_document_items(book)
        return self._assemble_documents(doc_items, "Extracting content (chunked)")

    def _get_document_items(self, book: epub.EpubBook) -> list[epub.EpubItem]:
        """Return EPUB document items in spine order, with an unordered fallback."""
        spine = book.spine if hasattr(book, "spine") else []
        doc_items = self._get_doc_items_from_spine(book, spine) if spine else []
        if doc_items:
            return doc_items

        logger.warning("No spine found in EPUB, falling back to unordered extraction")
        return [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]

    def _assemble_documents(self, doc_items: list[epub.EpubItem], description: str) -> str:
        """Merge ordered EPUB documents after assigning collision-free anchors.

        Target maps are built before content is emitted because a table of contents
        can link forward to a chapter whose IDs have not yet been encountered. Each
        source document is wrapped in a section to retain a stable destination when
        a link targets the file itself rather than a fragment within it.
        """
        if not doc_items:
            logger.info("No documents found in EPUB")
            return ""

        # Build every destination before rewriting links; a TOC can refer to a
        # later chapter that has not yet been appended to the output.
        self._build_document_targets(doc_items)
        chunks: list[str] = []
        for item in self._track_items(doc_items, description, "doc"):
            try:
                content = self._decode_document_content(item)
                self.total_docs_processed += 1
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning("Failed to extract document %s: %s", item.get_name(), e)
                continue

            if self.image_handler.image_map:
                content = self._replace_image_references(item.get_name(), content)
            # Preparing each chapter before joining prevents BeautifulSoup from
            # reparsing an ever-growing full-book document.
            chunks.append(self._prepare_document_content(item, content))

        html_content = "\n".join(chunks)
        if self.remove_cover:
            logger.info("Removing cover pages (--remove-cover set)...")
            html_content = self._remove_cover(html_content)
        else:
            logger.info("Preserving cover pages")

        if self.remove_toc:
            logger.info("Removing table of contents (--remove-toc set)...")
            html_content = self._remove_toc(html_content)
        else:
            logger.info("Preserving table of contents and rewriting internal links")

        return html_content

    @staticmethod
    def _normalize_document_path(path: str) -> str:
        """Normalize EPUB-internal paths without applying host OS path rules."""
        # EPUB package paths are POSIX paths regardless of the host platform.
        normalized = posixpath.normpath(unquote(path).replace("\\", "/"))
        return normalized.removeprefix("./")

    @staticmethod
    def _anchor_component(value: str) -> str:
        """Create a stable, URL-safe component for generated HTML IDs."""
        component = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return component or "item"

    def _build_document_targets(self, doc_items: Iterable[epub.EpubItem]) -> None:
        """Precompute unique page and fragment targets for merged EPUB documents.

        EPUB chapters often reuse IDs such as ``title`` or ``page1``. Prefixing IDs
        with each chapter's generated anchor makes them valid single-document
        targets without changing which source link resolves to which destination.
        """
        self.document_anchors = {}
        self.document_id_maps = {}
        used_anchors: set[str] = set()

        for item in doc_items:
            document_path = self._normalize_document_path(item.get_name())
            anchor_base = f"epub-{self._anchor_component(document_path)}"
            document_anchor = anchor_base
            suffix = 2
            while document_anchor in used_anchors:
                document_anchor = f"{anchor_base}-{suffix}"
                suffix += 1
            used_anchors.add(document_anchor)
            self.document_anchors[document_path] = document_anchor

            try:
                content = self._decode_document_content(item)
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning("Could not inspect anchors in %s: %s", item.get_name(), e)
                self.document_id_maps[document_path] = {}
                continue

            id_map: dict[str, str] = {}
            used_ids: set[str] = set()
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup.find_all(id=True):
                original_id = str(tag["id"])
                target_id = f"{document_anchor}--{self._anchor_component(original_id)}"
                duplicate = 2
                # A malformed chapter can repeat an ID. Preserve the first mapping
                # for incoming links while still making every emitted ID unique.
                while target_id in used_ids:
                    target_id = (
                        f"{document_anchor}--{self._anchor_component(original_id)}-{duplicate}"
                    )
                    duplicate += 1
                used_ids.add(target_id)
                id_map.setdefault(original_id, target_id)
            self.document_id_maps[document_path] = id_map

    def _prepare_document_content(self, item: epub.EpubItem, content: str) -> str:
        """Namespace IDs and rewrite internal links for one merged EPUB document."""
        document_path = self._normalize_document_path(item.get_name())
        document_anchor = self.document_anchors[document_path]
        id_map = self.document_id_maps[document_path]
        soup = BeautifulSoup(content, "html.parser")

        for tag in soup.find_all(id=True):
            original_id = str(tag["id"])
            if target_id := id_map.get(original_id):
                tag["id"] = target_id

        for link in soup.find_all("a", href=True):
            replacement = self._get_internal_link_target(document_path, str(link["href"]))
            if replacement:
                link["href"] = replacement

        if self.safe_html:
            self._sanitize_document(soup)

        body = soup.body
        # Discard the source document shell when present: the final output has one
        # optional shell, while this section retains only visible chapter content.
        content = "".join(str(child) for child in body.contents) if body else str(soup)
        escaped_source = html_module.escape(document_path, quote=True)
        return f'<section id="{document_anchor}" data-epub-source="{escaped_source}">{content}</section>'

    def _sanitize_document(self, soup: BeautifulSoup) -> None:
        """Remove browser-active EPUB markup and unsafe resource references."""
        # BeautifulSoup's type is intentionally kept local because EbookLib's
        # optional parser dependency is not part of the public API surface.
        dangerous_tags = {
            "base",
            "button",
            "canvas",
            "embed",
            "form",
            "iframe",
            "input",
            "link",
            "math",
            "meta",
            "object",
            "script",
            "style",
            "svg",
            "template",
            "video",
            "audio",
        }
        for tag in soup.find_all(dangerous_tags):
            tag.decompose()

        safe_url_attributes = {"href", "src", "poster", "xlink:href"}
        for tag in soup.find_all(True):
            for attribute in tuple(tag.attrs):
                attribute_name = str(attribute).lower()
                if attribute_name.startswith("on") or attribute_name == "style":
                    del tag.attrs[attribute]
                    continue
                if attribute_name not in safe_url_attributes:
                    continue
                value = tag.attrs[attribute]
                values: Sequence[object] = value if isinstance(value, list) else [value]
                if any(
                    not self._is_safe_url(tag.name, attribute_name, str(candidate))
                    for candidate in values
                ):
                    del tag.attrs[attribute]

            if tag.name in {"img", "source"}:
                for attribute in ("src",):
                    src_value = tag.get(attribute)
                    if src_value and not self._is_safe_url(tag.name, attribute, str(src_value)):
                        del tag.attrs[attribute]
                srcset = tag.get("srcset")
                if srcset:
                    candidates = self._split_srcset_candidates(str(srcset))
                    if any(
                        not self._is_safe_url(
                            tag.name, "srcset", candidate.strip().split(None, 1)[0]
                        )
                        for candidate in candidates
                        if candidate.strip()
                    ):
                        del tag.attrs["srcset"]

    @staticmethod
    def _is_safe_url(tag_name: str, attribute_name: str, value: str) -> bool:
        """Allow only inert local URLs, safe links, and generated raster data URLs."""
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.lower()
        if parsed.netloc:
            return False
        if tag_name == "a" and attribute_name == "href":
            return scheme in {"", "http", "https", "mailto", "tel"}
        if scheme == "":
            return True
        return scheme == "data" and parsed.path.lower().startswith(
            ("image/png", "image/jpeg", "image/gif", "image/webp")
        )

    def _get_internal_link_target(self, source_path: str, href: str) -> str | None:
        """Convert an EPUB-local hyperlink to its generated single-document target."""
        parsed = urlsplit(href)
        # Only rewrite local document/fragment links. Query-bearing or absolute
        # URLs may rely on semantics that do not survive a single-file conversion.
        if parsed.scheme or parsed.netloc or parsed.query or parsed.path.startswith("/"):
            return None

        target_path = source_path
        if parsed.path:
            target_path = self._normalize_document_path(
                posixpath.join(posixpath.dirname(source_path), parsed.path)
            )
        document_anchor = self.document_anchors.get(target_path)
        if not document_anchor:
            return None

        if parsed.fragment:
            target_id = self.document_id_maps.get(target_path, {}).get(unquote(parsed.fragment))
            if target_id:
                return f"#{target_id}"
        # A missing fragment can occur in imperfect EPUBs. Land at the chapter
        # section rather than preserving a link that cannot work after merging.
        return f"#{document_anchor}"

    def _decode_document_content(self, item: epub.EpubItem) -> str:
        """Decode EPUB markup, preferring fidelity while keeping conversion usable.

        EPUB content should be UTF-8, but real-world books occasionally violate that
        requirement. The fallback path uses ``chardet`` when installed and otherwise
        Latin-1 with replacement characters, favoring an inspectable HTML output
        over abandoning an entire conversion due to one malformed document.

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
                # Detection is optional: Latin-1 can decode every byte sequence,
                # giving users inspectable output when chardet is unavailable.
                try:
                    import chardet  # pylint: disable=import-outside-toplevel

                    detected = chardet.detect(item.get_content())
                    encoding = detected.get("encoding")
                    confidence = detected.get("confidence", 0)

                    # Do not trust a weak guess; a deterministic fallback is easier
                    # to diagnose than plausibly wrong text from a random encoding.
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

    def _extract_by_spine(self, book: epub.EpubBook) -> str:
        """Extract documents using the EPUB spine (reading order)."""
        html_content = ""

        spine = book.spine if hasattr(book, "spine") else []

        if not spine:
            return html_content

        doc_items = self._get_doc_items_from_spine(book, spine)

        if not doc_items:
            logger.info("No documents found in EPUB spine")
            return html_content

        for item in self._track_items(doc_items, "Extracting content", "doc"):
            try:
                content = self._decode_document_content(item)
                html_content += content + "\n"
                self.total_docs_processed += 1
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning("Failed to extract document %s: %s", item.get_name(), e)

        return html_content

    def _get_doc_items_from_spine(
        self, book: epub.EpubBook, spine: Iterable[tuple[str, str] | str]
    ) -> list[epub.EpubItem]:
        """Helper to collect document items from the spine."""
        doc_items: list[epub.EpubItem] = []
        for spine_item in spine:
            item_id = spine_item[0] if isinstance(spine_item, tuple) else spine_item
            try:
                item = book.get_item_with_id(item_id)
                if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                    doc_items.append(item)
            except (KeyError, AttributeError):
                pass
        return doc_items

    def _extract_all_documents(self, book: epub.EpubBook) -> str:
        """Fallback: extract all documents without spine order."""
        logger.warning("No spine found in EPUB, falling back to unordered extraction")
        html_content = ""
        items = list(book.get_items())
        doc_items = [item for item in items if item.get_type() == ebooklib.ITEM_DOCUMENT]

        if not doc_items:
            logger.info("No documents found in EPUB")
            return html_content

        for item in self._track_items(doc_items, "Extracting content", "doc"):
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
        soup = BeautifulSoup(content, "html.parser")
        removed_count = 0

        for nav in soup.find_all("nav"):
            epub_type = nav.get("epub:type")
            if epub_type:
                epub_type_str = str(epub_type) if epub_type else ""
                # ``epub:type`` may contain several whitespace-separated semantic
                # tokens; exact matching avoids removing values such as ``notoc``.
                if any(token == "toc" for token in epub_type_str.split()):
                    nav.decompose()
                    removed_count += 1

        for tag in soup.find_all(["nav", "div", "section", "article"]):
            class_attr = tag.get("class")
            if class_attr:
                classes = class_attr if isinstance(class_attr, list) else str(class_attr).split()
                # Match a class token, not a substring, so unrelated classes such
                # as ``toc-entry`` are preserved.
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
        soup = BeautifulSoup(content, "html.parser")
        removed_count = 0

        for tag in soup.find_all(["section", "div", "article"]):
            epub_type = tag.get("epub:type")
            if epub_type:
                epub_type_str = str(epub_type) if epub_type else ""
                # As with TOC removal, EPUB semantic values are token lists rather
                # than one fixed string.
                if any(token == "cover" for token in epub_type_str.split()):
                    tag.decompose()
                    removed_count += 1

        for tag in soup.find_all(["div", "section", "article"]):
            class_attr = tag.get("class")
            if class_attr:
                classes = class_attr if isinstance(class_attr, list) else str(class_attr).split()
                # Exact tokens limit removal to deliberate cover markers.
                if any(cls.lower() == "cover" for cls in classes):
                    tag.decompose()
                    removed_count += 1

        if removed_count > 0:
            logger.info("Removed %d cover elements", removed_count)

        return str(soup)

    def _parse_and_replace_srcset(self, source_path: str, srcset_str: str) -> str:
        """
        Parse srcset attribute and replace URLs while preserving descriptors.

        Follows the spec: split on commas not inside parentheses, then for each
        candidate split on whitespace into URL and descriptors, preserving order.
        Only replaces the URL token, leaving descriptors untouched.

        Args:
            source_path: EPUB path of the document containing the srcset attribute
            srcset_str: The srcset attribute value

        Returns:
            Processed srcset with replaced URLs and preserved descriptors
        """
        candidates = self._split_srcset_candidates(srcset_str)
        result_parts: list[str] = []

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue

            tokens = candidate.split(None, 1)
            if not tokens:
                result_parts.append(candidate)
                continue

            url = tokens[0].strip()
            descriptor = tokens[1] if len(tokens) > 1 else ""

            replacement = self._get_image_replacement(source_path, url)
            if replacement:
                if descriptor:
                    result_parts.append(f"{replacement} {descriptor}")
                else:
                    result_parts.append(replacement)
            else:
                # Preserve an unresolved candidate verbatim. A broken replacement
                # is worse than retaining the source URL for manual recovery.
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
        candidates: list[str] = []
        current: list[str] = []
        paren_depth = 0

        for char in srcset_str:
            if char == "(":
                paren_depth += 1
                current.append(char)
            elif char == ")":
                paren_depth -= 1
                current.append(char)
            # Commas inside functions (for example a data URL) are not candidate
            # separators, so only split at the top level.
            elif char == "," and paren_depth == 0:
                candidates.append("".join(current))
                current = []
            else:
                current.append(char)

        if current:
            candidates.append("".join(current))

        return candidates

    def _replace_image_references(self, source_path: str, content: str) -> str:
        """Replace source image URLs with the conversion's generated references.

        References are resolved relative to their XHTML document first, matching EPUB
        semantics. An unambiguous basename is only a compatibility fallback for
        malformed EPUBs; ambiguous assets retain their original URL to avoid a wrong
        image being substituted.
        """
        if not self.image_handler.image_map:
            return content

        soup = BeautifulSoup(content, "html.parser")

        image_tag_specs = [
            ("img", ["src"]),
            ("image", ["href", "xlink:href"]),
            ("source", ["srcset", "src"]),
        ]

        unresolved_count = 0

        for tag_name, attributes in image_tag_specs:
            tags = soup.find_all(tag_name)
            for tag in tags:
                for attr in attributes:
                    attr_value = tag.get(attr)
                    if not attr_value:
                        continue

                    attr_value_str = str(attr_value)

                    if attr == "srcset":
                        # ``srcset`` contains several URL/descriptor pairs and
                        # cannot be treated like a single ``src`` attribute.
                        processed_srcset = self._parse_and_replace_srcset(
                            source_path, attr_value_str
                        )
                        tag[attr] = processed_srcset
                    else:
                        replacement = self._get_image_replacement(source_path, attr_value_str)
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

    def _get_image_replacement(self, source_path: str, url: str) -> str | None:
        """
        Look up an image URL relative to an EPUB document and return its replacement.

        Implementation order:
        1. Exact match after resolving the URL against the source document path
        2. Exact match against the original image item path
        3. Unambiguous basename lookup (only if single entry exists)

        Returns None for ambiguous basenames or no matches.

        Args:
            source_path: EPUB path of the document containing the image reference
            url: The URL/path to look up

        Returns:
            The replacement URL/path, or None if no unique mapping exists
        """
        parsed = urlsplit(url)
        # Remote, root-relative, and empty URLs are outside the EPUB manifest and
        # must remain untouched rather than being resolved against a chapter path.
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
            return None

        normalized_source_path = self._normalize_document_path(source_path)
        # EPUB references are relative to the XHTML file that contains them, not
        # to the archive root or the output HTML file.
        resolved_path = self._normalize_document_path(
            posixpath.join(posixpath.dirname(normalized_source_path), parsed.path)
        )

        for image_name, image_url in self.image_handler.image_map.items():
            if self._normalize_document_path(image_name) == resolved_path:
                return image_url

        # Retain compatibility with references already expressed as EPUB-internal
        # paths. This is less precise than document-relative resolution, so it is
        # intentionally attempted only after that canonical form.
        original_path = self._normalize_document_path(parsed.path)
        for image_name, image_url in self.image_handler.image_map.items():
            if self._normalize_document_path(image_name) == original_path:
                return image_url

        # Step 3: Use basename matching only when it cannot select the wrong image.
        url_basename = posixpath.basename(resolved_path).lower()
        if not url_basename:
            return None

        if url_basename in self.image_handler.basename_map:
            candidates = self.image_handler.basename_map[url_basename]
            if len(candidates) == 1:
                return candidates[0][1]
            if len(candidates) > 1:
                logger.warning(
                    "Ambiguous image reference: '%s' matches multiple files with basename '%s' "
                    "from different folders (%s). Skipping replacement to avoid incorrect substitution.",
                    url,
                    url_basename,
                    ", ".join(orig for orig, _ in candidates),
                )
                return None

        return None

    def _write_html(self, content: str, title: str | None = None) -> None:
        """Write HTML content to output file."""
        self.html_path.parent.mkdir(parents=True, exist_ok=True)

        if self.wrap_html:
            # Fragment output is intentional by default: callers may embed it in
            # an existing page. Only synthesize a document shell when requested.
            content = self._wrap_in_html_structure(content, title=title)

        with open(self.html_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _log_conversion_summary(self) -> None:
        """Log a comprehensive summary of extraction decisions and processing statistics."""
        images_dir = None
        if self.image_handler.strategy == "extract":
            # This is reported only for extracted assets; embedded images have no
            # separate location that would help the user find conversion output.
            images_dir = str(self.image_handler.output_dir)

        summary = Table.grid(padding=(0, 1))
        summary.add_column(style="bold cyan", justify="right")
        summary.add_column()
        summary.add_row("Documents", str(self.total_docs_processed))
        summary.add_row("Images processed", str(self.total_images_processed))
        summary.add_row("Embedded", str(self.embedded_images_count))
        summary.add_row("Extracted", str(self.extracted_images_count))
        summary.add_row("Skipped", str(self.skipped_images_count))
        if images_dir:
            summary.add_row("Images directory", images_dir)
        if self.decode_fallbacks_count > 0:
            summary.add_row("Encoding fallbacks", str(self.decode_fallbacks_count))
            logger.info(
                "Note: %d document(s) required encoding fallback detection. "
                "For better accuracy, consider installing chardet: pip install chardet",
                self.decode_fallbacks_count,
            )
        summary.add_row("HTML output", str(self.html_path))
        self.ui_console.print(
            Panel(
                summary,
                title="[bold green]Conversion complete[/]",
                subtitle="Your HTML is ready to read.",
                border_style="green",
            )
        )

    def _wrap_in_html_structure(self, content: str, title: str | None = None) -> str:
        """Return a standalone HTML5 document around converted content.

        Caller-provided CSS replaces the small readability-oriented default rather
        than being appended to it, so custom styles fully control presentation.
        """
        import textwrap  # pylint: disable=import-outside-toplevel

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
    <title>{html_module.escape(page_title, quote=True)}</title>
    {css_block}
</head>
<body>
    {content}
</body>
</html>
"""
        return html


def main() -> None:
    """Run the CLI, validate filesystem options, and report conversion outcomes.

    This boundary owns user-facing rendering and process exit codes. Conversion
    classes raise normal Python exceptions so they remain reusable by callers that
    import this module instead of invoking it as a script.
    """
    parser = RichArgumentParser(
        description="Convert an EPUB file to HTML format with flexible image handling."
    )

    parser.add_argument("epub_path", type=str, help="Path to the input EPUB file")

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="output.html",
        help="Path to output HTML file (relative paths are resolved from the current working directory)",
    )

    parser.add_argument(
        "-s",
        "--strategy",
        choices=["embed", "extract"],
        default="embed",
        help="Image handling: 'embed' for base64 or 'extract' for separate files",
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
        "--remove-toc",
        action="store_true",
        help="Remove table of contents elements; otherwise preserve the TOC and rewrite its links",
    )

    parser.add_argument(
        "--remove-cover",
        action="store_true",
        help="Remove cover page elements; otherwise preserve the cover",
    )

    parser.add_argument(
        "--images-dir-name",
        type=str,
        default="{stem}_files",
        help="Directory name pattern for extracted images when using --strategy extract. Use {stem} as placeholder for the HTML filename stem",
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
        "--safe-mode",
        action="store_true",
        help="Sanitize active HTML/CSS and unsafe resource URLs before emitting output (use for untrusted EPUBs)",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing HTML output and extracted-image directory",
    )

    parser.add_argument(
        "--max-archive-entries",
        type=int,
        default=ArchiveLimits.max_entries,
        help="Maximum number of files allowed in the EPUB archive",
    )
    parser.add_argument(
        "--max-compressed-bytes",
        type=int,
        default=ArchiveLimits.max_compressed_bytes,
        help="Maximum total compressed size of the EPUB archive in bytes",
    )
    parser.add_argument(
        "--max-expanded-bytes",
        type=int,
        default=ArchiveLimits.max_expanded_bytes,
        help="Maximum total expanded size of the EPUB archive in bytes",
    )
    parser.add_argument(
        "--max-entry-bytes",
        type=int,
        default=ArchiveLimits.max_entry_bytes,
        help="Maximum expanded size of one EPUB archive member in bytes",
    )
    parser.add_argument(
        "--max-compression-ratio",
        type=float,
        default=ArchiveLimits.max_compression_ratio,
        help="Maximum allowed expanded-to-compressed size ratio for one archive member",
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=ArchiveLimits.max_documents,
        help="Maximum number of document resources allowed in the EPUB",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=ArchiveLimits.max_images,
        help="Maximum number of image resources allowed in the EPUB",
    )
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        default=ArchiveLimits.max_output_bytes,
        help="Maximum size of the generated HTML and extracted assets in bytes",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level; otherwise DEBUG is used with -v/--verbose and INFO without it",
    )

    parser.add_argument(
        "--log-format",
        type=str,
        default="- %(message)s",
        help="Set logging message format",
    )

    args = parser.parse_args()

    if args.log_level:
        # An explicit level takes precedence over the convenient verbose shortcut.
        log_level = getattr(logging, args.log_level)
    elif args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format=args.log_format,
        handlers=[
            CompactRichHandler(
                console=console,
                show_time=False,
                rich_tracebacks=args.verbose,
                markup=True,
            )
        ],
    )

    css_content = None
    if args.css:
        css_path = Path(args.css)
        if not css_path.exists():
            console.print(
                Panel(
                    f"CSS file not found: [bold]{css_path}[/]",
                    title="[bold red]Conversion cannot start[/]",
                    border_style="red",
                )
            )
            sys.exit(1)
        css_content = css_path.read_text(encoding="utf-8")

    # Custom CSS has nowhere valid to live in a fragment, so it implicitly opts
    # into a complete HTML shell even when ``--wrap`` was not supplied.
    wrap_html = args.wrap or (args.css is not None)

    epub_path = Path(args.epub_path)
    if not epub_path.is_file():
        console.print(
            Panel(
                f"EPUB file not found or is not a regular file: [bold]{epub_path}[/]",
                title="[bold red]Conversion cannot start[/]",
                border_style="red",
            )
        )
        sys.exit(1)

    # Resolve once so the plan, converter, and extracted-images location all use
    # the same absolute base even when the current directory later changes.
    output_path = Path(args.output).resolve()
    logger.info("Resolved output path: %s", output_path)

    # Validate the expanded name before creating the directory: otherwise extract
    # mode could turn the requested HTML file path into a conflicting directory.
    images_dir_name = args.images_dir_name
    try:
        final_images_dir_name = images_dir_name.format(stem=output_path.stem)
    except (KeyError, ValueError, IndexError) as error:
        console.print(
            Panel(
                f"Invalid images directory pattern: [bold]{error}[/]",
                title="[bold red]Invalid output layout[/]",
                border_style="red",
            )
        )
        sys.exit(2)
    if (
        not final_images_dir_name
        or Path(final_images_dir_name).name != final_images_dir_name
        or final_images_dir_name in {".", ".."}
    ):
        console.print(
            Panel(
                "Images directory name must be a non-empty basename and may use only the {stem} placeholder.",
                title="[bold red]Invalid output layout[/]",
                border_style="red",
            )
        )
        sys.exit(2)
    if final_images_dir_name == output_path.name:
        console.print(
            Panel(
                "Images directory name "
                f"([bold]{final_images_dir_name}[/]) cannot equal the HTML filename "
                f"([bold]{output_path.name}[/]).",
                title="[bold red]Path collision[/]",
                border_style="red",
            )
        )
        sys.exit(1)

    show_progress = True
    if args.no_progress:
        show_progress = False
    elif args.force_progress:
        show_progress = True
    else:
        # Rich progress redraws cleanly only on an interactive terminal; avoid
        # polluting redirected output unless the caller explicitly forces it.
        show_progress = sys.stderr.isatty()

    plan = Table.grid(padding=(0, 1))
    plan.add_column(style="bold cyan", justify="right")
    plan.add_column()
    plan.add_row("Source", str(epub_path))
    plan.add_row("Destination", str(output_path))
    plan.add_row("Images", args.strategy)
    plan.add_row("Document shell", "enabled" if wrap_html else "fragment only")
    plan.add_row("TOC", "remove" if args.remove_toc else "preserve")
    plan.add_row("Cover", "remove" if args.remove_cover else "preserve")
    plan.add_row("Content", "safe mode" if args.safe_mode else "source fidelity")
    plan.add_row("Processing", "chunked" if args.chunked else "standard")
    console.print(
        Group(
            Panel.fit(
                Text("EPUB → HTML", style="bold bright_cyan"),
                border_style="bright_cyan",
            ),
            Panel(plan, border_style="blue"),
        )
    )

    try:
        archive_limits = ArchiveLimits(
            max_entries=args.max_archive_entries,
            max_compressed_bytes=args.max_compressed_bytes,
            max_expanded_bytes=args.max_expanded_bytes,
            max_entry_bytes=args.max_entry_bytes,
            max_compression_ratio=args.max_compression_ratio,
            max_documents=args.max_documents,
            max_images=args.max_images,
            max_output_bytes=args.max_output_bytes,
        )
        converter = EpubConverter(
            epub_path=args.epub_path,
            html_path=output_path,
            image_strategy=args.strategy,
            wrap_html=wrap_html,
            css=css_content,
            show_progress=show_progress,
            allow_unknown_mime=args.allow_unknown_mime,
            remove_toc=args.remove_toc,
            remove_cover=args.remove_cover,
            images_dir_name=images_dir_name,
            chunked=args.chunked,
            safe_html=args.safe_mode,
            force=args.force,
            archive_limits=archive_limits,
        )
        converter.convert()

        if args.strategy == "extract":
            final_dir_name = args.images_dir_name.format(stem=output_path.stem)
            images_dir = output_path.parent / final_dir_name
            logger.info("Images extracted to: %s", images_dir)
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Conversion libraries can raise format-specific exceptions. Keep the CLI
        # boundary friendly while ``--verbose`` still exposes the traceback.
        console.print(
            Panel(
                str(error),
                title="[bold red]Conversion failed[/]",
                subtitle="Use --verbose for diagnostic details.",
                border_style="red",
            )
        )
        if args.verbose:
            console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    main()
