"""Read-only EPUB inspection for planning conversions and diagnosing fidelity gaps."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ebooklib import epub

from converter import document_items, language, preflight_archive, title
from model import ConversionOptions


@dataclass(frozen=True)
class InspectionResult:
    """Serializable facts gathered without creating output files."""

    input_path: Path
    title: str | None
    language: str
    spine: tuple[str, ...]
    media_types: dict[str, int]
    asset_bytes: int
    fixed_layout: bool
    unsupported_features: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["input_path"] = str(self.input_path)
        return payload


def inspect_epub(path: Path, options: ConversionOptions) -> InspectionResult:
    """Preflight and inspect a publication without staging conversion output."""
    inspected_options = ConversionOptions(
        input_path=path, output_path=options.output_path, archive_limits=options.archive_limits
    )
    preflight_archive(path, inspected_options)
    book = epub.read_epub(str(path))
    items = list(book.get_items())
    media_types = Counter(str(item.media_type or "unknown") for item in items)
    names = [item.get_name().lower() for item in items]
    types = set(media_types)
    unsupported: list[str] = []
    for marker, label in (
        ("image/svg+xml", "SVG"),
        ("application/font", "fonts"),
        ("audio/", "audio"),
        ("video/", "video/"),
    ):
        if any(value.startswith(marker) for value in types):
            unsupported.append(label)
    if any("mathml" in name for name in names):
        unsupported.append("MathML")
    fixed = any("rendition:layout" in name or "fixed" in name for name in names)
    return InspectionResult(
        path,
        title(book),
        language(book),
        tuple(item.get_name() for item in document_items(book)),
        dict(sorted(media_types.items())),
        sum(len(item.get_content()) for item in items),
        fixed,
        tuple(unsupported),
    )
