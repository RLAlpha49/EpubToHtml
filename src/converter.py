"""Public EPUB conversion service and archive preflight policy."""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Iterator
from html import escape
from pathlib import Path
from time import monotonic

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from html_transform import (
    DocumentTarget,
    _extract_epub_metadata,
    build_targets,
    decode_document,
    prepare_document,
    rewrite_css_urls,
    wrap_document,
)
from images import EmbeddedImageOutput, ExtractedImageOutput, ImageIndex, ImageOutput
from model import (
    ArchiveLimitError,
    ConversionCancelledError,
    ConversionError,
    ConversionObserver,
    ConversionOptions,
    ConversionResult,
    DocumentTransformConfig,
    EpubReader,
    InvalidEpubError,
    OutputValidationError,
    WarningCollector,
)
from output import StagedOutput
from reader import EbookLibReader


def preflight_archive(path: Path, options: ConversionOptions) -> None:
    """Check that an input is a regular readable EPUB ZIP within resource limits."""
    if not path.is_file():
        raise InvalidEpubError(f"EPUB file not found or is not a regular file: {path}")
    limits = options.archive_limits
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_entries:
                raise ArchiveLimitError("Archive contains more entries than allowed.")
            compressed = expanded = 0
            names: set[str] = set()
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                if not name or name.startswith("/") or ".." in name.split("/") or "\x00" in name:
                    raise InvalidEpubError(
                        f"Archive contains unsafe member name: {entry.filename!r}"
                    )
                if stat.S_ISLNK((entry.external_attr >> 16) & 0xFFFF):
                    raise InvalidEpubError(
                        f"Archive contains symbolic link member: {entry.filename!r}"
                    )
                if name in names:
                    raise InvalidEpubError(f"Archive contains duplicate member: {entry.filename!r}")
                names.add(name)
                compressed += entry.compress_size
                expanded += entry.file_size
                if entry.file_size > limits.max_entry_bytes:
                    raise ArchiveLimitError(
                        f"Archive member exceeds entry limit: {entry.filename!r}"
                    )
                if (entry.compress_size == 0 and entry.file_size > 0) or (
                    entry.compress_size > 0
                    and entry.file_size / entry.compress_size > limits.max_compression_ratio
                ):
                    raise ArchiveLimitError(
                        f"Archive member exceeds compression-ratio limit: {entry.filename!r}"
                    )
            if compressed > limits.max_compressed_bytes or expanded > limits.max_expanded_bytes:
                raise ArchiveLimitError("Archive exceeds configured size limits.")
            missing = {"mimetype", "META-INF/container.xml"} - names
            if missing:
                raise InvalidEpubError(
                    f"EPUB archive is missing required member(s): {', '.join(sorted(missing))}"
                )
    except zipfile.BadZipFile as error:
        raise InvalidEpubError(f"Input is not a valid ZIP/EPUB archive: {error}") from error


def _title(book: epub.EpubBook) -> str | None:
    try:
        value = book.get_metadata("DC", "title")[0]
        if isinstance(value, tuple):
            return value[0]
        if isinstance(value, str):
            return value
        return None
    except (AttributeError, IndexError, TypeError):
        return None


def _language(book: epub.EpubBook) -> str:
    """Return EPUB language metadata when present, with English as the shell fallback."""
    try:
        value = book.get_metadata("DC", "language")[0]
        value = value[0] if isinstance(value, tuple) else value
        return value if isinstance(value, str) else "en"
    except (AttributeError, IndexError, TypeError):
        return "en"


def _metadata(book: epub.EpubBook) -> dict[str, str]:
    """Extract Dublin Core metadata from the EPUB."""
    metadata: dict[str, str] = {}
    for key in ("creator", "publisher", "date", "identifier", "rights", "description", "subject"):
        try:
            value = book.get_metadata("DC", key)[0]
            if isinstance(value, tuple):
                value = value[0]
            if isinstance(value, str) and value.strip():
                metadata[key] = value.strip()
        except (AttributeError, IndexError, TypeError):
            pass
    return metadata


def title(book: epub.EpubBook) -> str | None:
    """Return the publication title for callers that inspect an EPUB."""
    return _title(book)


def language(book: epub.EpubBook) -> str:
    """Return the publication language for callers that inspect an EPUB."""
    return _language(book)


def _documents(book: epub.EpubBook) -> list[epub.EpubItem]:
    ordered: list[epub.EpubItem] = []
    for entry in book.spine:
        item_id: str = entry[0] if isinstance(entry, tuple) else entry
        item = book.get_item_with_id(item_id)
        if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
            ordered.append(item)
    return ordered or [
        item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT
    ]


def document_items(book: epub.EpubBook) -> list[epub.EpubItem]:
    """Return document items in spine order for callers that inspect an EPUB."""
    return _documents(book)


def _selected_documents(
    documents: list[epub.EpubItem], options: ConversionOptions
) -> list[epub.EpubItem]:
    """Apply a one-based inclusive spine range before document targets are allocated."""
    if not options.spine_range:
        return documents
    start, end = options.spine_range
    return documents[(start - 1 if start else 0) : end]


def _check_cancelled(options: ConversionOptions, started_at: float) -> None:
    if options.cancellation_requested and options.cancellation_requested():
        raise ConversionCancelledError("Conversion was cancelled.")
    if options.deadline_seconds and monotonic() - started_at >= options.deadline_seconds:
        raise ConversionCancelledError("Conversion deadline expired.")


def _validate_staged_html(path: Path) -> None:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    ids = [str(tag["id"]) for tag in soup.find_all(id=True)]
    if len(ids) != len(set(ids)):
        raise OutputValidationError("Generated output contains duplicate HTML IDs.")
    known = set(ids)
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if href.startswith("#") and href[1:] and href[1:] not in known:
            raise OutputValidationError(f"Generated output has unresolved local link: {href}")
    for tag in soup.find_all(src=True):
        source = str(tag["src"])
        if source and not source.startswith(("data:", "http:", "https:", "//")):
            raise OutputValidationError(f"Generated output has unresolved local resource: {source}")


def _process_images(
    images: list[epub.EpubItem],
    resources: list[epub.EpubItem],
    options: ConversionOptions,
    staged: StagedOutput,
    index: ImageIndex,
    started_at: float,
    diagnostics: WarningCollector,
    observer: ConversionObserver | None,
) -> tuple[int, int]:
    """Register images and extractable resources, returning (processed, skipped)."""
    strategy: ImageOutput
    if staged.images_path:
        strategy = ExtractedImageOutput(staged.images_path, options.safe_html)
    else:
        strategy = EmbeddedImageOutput(options.safe_html, options.stable_mime_types)
    processed_images = skipped = 0
    if observer:
        observer.phase("Processing images", len(images), "img")
    for image in images:
        _check_cancelled(options, started_at)
        try:
            index.add(strategy.register(image))
            processed_images += 1
        except (OSError, ValueError) as error:
            skipped += 1
            diagnostics.add("skipped-image", str(error), image.get_name())
        finally:
            if observer:
                observer.advance()
    if options.image_strategy == "extract":
        for resource in resources:
            media_type = str(resource.media_type or "")
            policy = options.font_policy if "font" in media_type else options.media_policy
            if policy == "extract":
                try:
                    index.add(strategy.register(resource))
                except (OSError, ValueError) as error:
                    diagnostics.add("skipped-resource", str(error), resource.get_name())
            elif policy == "preserve":
                diagnostics.add(
                    "preserved-resource-reference",
                    "Resource reference was retained; use extract mode to copy it beside HTML.",
                    resource.get_name(),
                )
            else:
                diagnostics.add(
                    "omitted-resource", "Resource omitted by policy.", resource.get_name()
                )
    return processed_images, skipped


def _process_stylesheets(
    stylesheets: list[epub.EpubItem],
    options: ConversionOptions,
    index: ImageIndex,
    diagnostics: WarningCollector,
) -> str:
    """Rewrite and inline internal stylesheets, returning the merged CSS."""
    if not (options.preserve_internal_css and not options.safe_html):
        return ""
    css_parts: list[str] = []
    for stylesheet in stylesheets:
        try:
            css_parts.append(
                rewrite_css_urls(
                    stylesheet.get_content().decode("utf-8"), stylesheet.get_name(), index
                )
            )
        except UnicodeDecodeError:
            diagnostics.add("skipped-stylesheet", "Stylesheet is not UTF-8.", stylesheet.get_name())
    return "\n".join(css_parts)


def _decode_documents(
    documents: list[epub.EpubItem],
    options: ConversionOptions,
    started_at: float,
    diagnostics: WarningCollector,
    observer: ConversionObserver | None,
) -> tuple[list[tuple[epub.EpubItem, str]], int]:
    """Decode documents and return (decoded_pairs, skipped_count)."""
    decoded: list[tuple[epub.EpubItem, str]] = []
    skipped_documents = 0
    if observer:
        observer.phase("Decoding documents", len(documents), "doc")
    for document in documents:
        _check_cancelled(options, started_at)
        try:
            content, warning = decode_document(document)
            decoded.append((document, content))
            if warning:
                diagnostics.add(warning.code, warning.message, warning.location)
        except (OSError, ValueError) as error:
            skipped_documents += 1
            diagnostics.add("skipped-document", str(error), document.get_name())
        if observer:
            observer.advance()
    return decoded, skipped_documents


def _prepare_sections(
    decoded: list[tuple[epub.EpubItem, str]],
    targets: dict[str, DocumentTarget],
    index: ImageIndex,
    options: ConversionOptions,
    started_at: float,
    diagnostics: WarningCollector,
    observer: ConversionObserver | None,
) -> Iterator[str]:
    """Yield prepared HTML sections from decoded documents."""
    if observer:
        observer.phase("Extracting content", len(decoded), "doc")
    for document, content in decoded:
        _check_cancelled(options, started_at)
        section, warnings = prepare_document(
            document,
            content,
            targets,
            index,
            options.remove_toc,
            options.remove_cover,
            options.safe_html,
            options.exclude_content,
            options.svg_policy,
            options.mathml_policy,
        )
        for warning in warnings:
            diagnostics.add(warning.code, warning.message, warning.location)
        if observer:
            observer.advance()
        yield section


def _write_output(
    sections: Iterator[str],
    staged: StagedOutput,
    options: ConversionOptions,
    book: epub.EpubBook,
    internal_css: str,
) -> None:
    """Write sections to staged output according to output options."""
    with staged.open_html("\r\n" if options.newline == "crlf" else "\n") as output:
        if options.wrap_html and options.chunked and not options.navigation:
            styles = (
                "\n".join(value for value in (options.css, internal_css) if value)
                or f"body {{ font-family: {options.reader_font_family}; line-height: 1.6; max-width: {options.reader_max_width}; margin: 0 auto; padding: clamp(1rem, 4vw, 2rem); }} img {{ max-width: 100%; height: auto; }}"
            )
            metadata_tags = _extract_epub_metadata(book)
            output.write(
                f'<!DOCTYPE html>\n<html lang="{escape(_language(book), quote=True)}">'
                f'<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">'
                f"<title>{escape(_title(book) or 'EPUB Document', quote=True)}</title>"
                f"{metadata_tags}"
                f"<style>{styles}</style></head>"
                f'<body id="top"><a class="skip-link" href="#main-content">Skip to content</a>'
                f'<main id="main-content" tabindex="-1">'
            )
            for section in sections:
                output.write(section + "\n")
            output.write("</main></body></html>\n")
        elif options.wrap_html:
            output.write(
                wrap_document(
                    "\n".join(sections),
                    _title(book),
                    "\n".join(value for value in (options.css, internal_css) if value) or None,
                    _language(book),
                    options.navigation,
                    options.reader_max_width,
                    options.reader_font_family,
                    book,
                )
            )
        elif options.chunked:
            for section in sections:
                output.write(section + "\n")
        else:
            output.write("\n".join(sections))


def convert(
    options: ConversionOptions,
    observer: ConversionObserver | None = None,
    reader: EpubReader | None = None,
) -> ConversionResult:
    """Convert one EPUB according to an immutable policy and return its outcome."""
    options.validate()
    started_at = monotonic()
    _check_cancelled(options, started_at)
    if observer:
        observer.phase("Validating EPUB archive")
    preflight_archive(options.input_path, options)
    diagnostics = WarningCollector()
    if observer:
        observer.phase("Reading EPUB")
    book = (reader or EbookLibReader()).read(options.input_path)
    _check_cancelled(options, started_at)
    items = list(book.get_items())
    documents = _selected_documents(_documents(book), options)
    images = [
        item for item in items if item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER)
    ]
    resources = [
        item
        for item in items
        if str(item.media_type or "").startswith(("audio/", "video/", "font/", "application/font"))
    ]
    stylesheets = [item for item in items if str(item.media_type or "").lower() == "text/css"]
    if len(documents) > options.archive_limits.max_documents:
        raise ArchiveLimitError("EPUB contains more documents than allowed.")
    if len(images) > options.archive_limits.max_images:
        raise ArchiveLimitError("EPUB contains more images than allowed.")
    images_name = (
        options.images_dir_name.format(stem=options.output_path.stem)
        if options.image_strategy == "extract"
        else None
    )

    with StagedOutput(options.output_path, images_name, options.force) as staged:
        index = ImageIndex()
        processed_images, skipped = _process_images(
            images, resources, options, staged, index, started_at, diagnostics, observer
        )
        internal_css = _process_stylesheets(stylesheets, options, index, diagnostics)
        decoded, skipped_documents = _decode_documents(
            documents, options, started_at, diagnostics, observer
        )
        targets = build_targets(decoded)
        sections = _prepare_sections(
            decoded, targets, index, options, started_at, diagnostics, observer
        )
        if observer:
            observer.phase("Writing output")
        _write_output(sections, staged, options, book, internal_css)
        if staged.size() > options.archive_limits.max_output_bytes:
            raise ArchiveLimitError("Generated output exceeds configured output limit.")
        if options.validate_output and staged.html_path:
            _validate_staged_html(staged.html_path)
        if options.fail_on_warning and diagnostics.warnings:
            raise ConversionError(
                "Conversion produced warnings and --fail-on-warning was requested."
            )
        staged.commit()

    return ConversionResult(
        options.output_path,
        options.output_path.parent / images_name if images_name else None,
        len(documents),
        processed_images,
        skipped,
        skipped_documents,
        sum(warning.code == "decode-fallback" for warning in diagnostics.warnings),
        diagnostics.warnings,
        diagnostics.duration_seconds,
        options.chunked,
        options.safe_html,
        options.input_path.stat().st_size,
        options.output_path.stat().st_size,
        chapters=tuple(item.get_name() for item, _ in decoded),
    )
