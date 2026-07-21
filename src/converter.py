"""Public EPUB conversion service and archive preflight policy."""

from __future__ import annotations

import stat
import zipfile
from html import escape
from pathlib import Path

import ebooklib
from ebooklib import epub

from html_transform import build_targets, decode_document, prepare_document, wrap_html
from images import EmbeddedImageOutput, ExtractedImageOutput, ImageIndex, ImageOutput
from model import (
    ArchiveLimitError,
    ConversionObserver,
    ConversionOptions,
    ConversionResult,
    InvalidEpubError,
    WarningCollector,
)
from output import StagedOutput


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
                if entry.compress_size == 0 < entry.file_size or (
                    entry.compress_size
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


def _documents(book: epub.EpubBook) -> list[epub.EpubItem]:
    ordered = []
    for entry in getattr(book, "spine", []):
        item = book.get_item_with_id(entry[0] if isinstance(entry, tuple) else entry)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            ordered.append(item)
    return ordered or [
        item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT
    ]


def convert(
    options: ConversionOptions, observer: ConversionObserver | None = None
) -> ConversionResult:
    """Convert one EPUB according to an immutable policy and return its outcome."""
    options.validate()
    if observer:
        observer.phase("Validating EPUB archive")
    preflight_archive(options.input_path, options)
    diagnostics = WarningCollector()
    if observer:
        observer.phase("Reading EPUB")
    book = epub.read_epub(str(options.input_path))
    items = list(book.get_items())
    documents = _documents(book)
    images = [
        item for item in items if item.get_type() in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER)
    ]
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
        strategy: ImageOutput
        if staged.images_path:
            strategy = ExtractedImageOutput(staged.images_path)
        else:
            strategy = EmbeddedImageOutput()
        index = ImageIndex()
        processed_images = skipped = 0
        if observer:
            observer.phase("Processing images", len(images), "img")
        for image in images:
            try:
                index.add(strategy.register(image))
                processed_images += 1
            except (OSError, ValueError) as error:
                skipped += 1
                diagnostics.add("skipped-image", str(error), image.get_name())
            finally:
                if observer:
                    observer.advance()

        decoded: list[tuple[epub.EpubItem, str]] = []
        if observer:
            observer.phase("Decoding documents", len(documents), "doc")
        for document in documents:
            content, warning = decode_document(document)
            decoded.append((document, content))
            if warning:
                diagnostics.add(warning.code, warning.message, warning.location)
            if observer:
                observer.advance()
        targets = build_targets(decoded)

        def sections():
            if observer:
                observer.phase("Extracting content", len(decoded), "doc")
            for document, content in decoded:
                section, warnings = prepare_document(
                    document,
                    content,
                    targets,
                    index,
                    options.remove_toc,
                    options.remove_cover,
                    options.safe_html,
                )
                for warning in warnings:
                    diagnostics.add(warning.code, warning.message, warning.location)
                if observer:
                    observer.advance()
                yield section

        if observer:
            observer.phase("Writing output")
        with staged.open_html() as output:
            if options.wrap_html and options.chunked:
                styles = (
                    options.css
                    or "body { font-family: Georgia, serif; line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 20px; } img { max-width: 100%; height: auto; }"
                )
                output.write(
                    f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{escape(_title(book) or "EPUB Document", quote=True)}</title><style>{styles}</style></head><body>'
                )
                for section in sections():
                    output.write(section + "\n")
                output.write("</body></html>\n")
            elif options.wrap_html:
                output.write(wrap_html("\n".join(sections()), _title(book), options.css))
            elif options.chunked:
                for section in sections():
                    output.write(section + "\n")
            else:
                output.write("\n".join(sections()))
        if staged.size() > options.archive_limits.max_output_bytes:
            raise ArchiveLimitError("Generated output exceeds configured output limit.")
        staged.commit()

    return ConversionResult(
        options.output_path,
        options.output_path.parent / images_name if images_name else None,
        len(documents),
        processed_images,
        skipped,
        sum(warning.code == "decode-fallback" for warning in diagnostics.warnings),
        diagnostics.warnings,
        diagnostics.duration_seconds,
        options.chunked,
        options.safe_html,
    )
