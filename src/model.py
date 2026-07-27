"""Public conversion policy, result, diagnostics, and domain errors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Protocol

WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"}
WINDOWS_RESERVED_NAMES.update(f"com{number}" for number in range(1, 10))
WINDOWS_RESERVED_NAMES.update(f"lpt{number}" for number in range(1, 10))


class ConversionError(Exception):
    """Base class for expected conversion failures."""


class InvalidEpubError(ConversionError):
    """Raised when an input cannot be accepted as an EPUB."""


class ArchiveLimitError(ConversionError):
    """Raised when an EPUB archive violates a configured resource policy."""


class OutputError(ConversionError):
    """Raised when output cannot be written or committed safely."""


class ConversionCancelledError(ConversionError):
    """Raised when a caller cancels conversion or its deadline expires."""


class OutputValidationError(ConversionError):
    """Raised when staged HTML fails requested integrity checks."""


class ConversionObserver(Protocol):
    """Receive optional conversion status events without coupling to a UI."""

    def phase(self, description: str, total: int | None = None, unit: str = "") -> None: ...

    def advance(self) -> None: ...

    def phase_complete(self) -> None: ...


class EpubReader(Protocol):
    """Abstract EPUB reader so the converter does not depend on a specific backend.

    A concrete implementation (e.g. wrapping ``ebooklib``) is injected at the
    top level; tests can supply an in-memory fake.
    """

    def read(self, path: Path, timeout: float | None = None) -> Any: ...


@dataclass(frozen=True)
class ArchiveLimits:
    """Resource limits applied before and during EPUB conversion."""

    max_entries: int = 10_000
    max_compressed_bytes: int = 256 * 1024 * 1024
    max_expanded_bytes: int = 1024 * 1024 * 1024
    max_entry_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 1_000.0
    max_documents: int = 5_000
    max_images: int = 10_000
    max_output_bytes: int = 1024 * 1024 * 1024

    def validate(self) -> None:
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


@dataclass(frozen=True)
class DocumentTransformConfig:
    """Document filtering and policy settings used by the transformation seam."""

    remove_toc: bool = False
    remove_cover: bool = False
    safe_html: bool = False
    excluded: frozenset[str] = field(default_factory=frozenset[str])
    svg_policy: Literal["omit", "extract", "preserve"] = "omit"
    mathml_policy: Literal["omit", "preserve"] = "omit"
    preserve_scripts: bool = False
    resolve_switch: bool = True


@dataclass(frozen=True)
class ConversionOptions:
    """Validated immutable configuration for a conversion request."""

    input_path: Path
    output_path: Path
    image_strategy: Literal["embed", "extract"] = "embed"
    wrap_html: bool = False
    css: str | None = None
    remove_toc: bool = False
    remove_cover: bool = False
    images_dir_name: str = "{stem}_files"
    chunked: bool = False
    safe_html: bool = False
    force: bool = False
    archive_limits: ArchiveLimits = field(default_factory=ArchiveLimits)
    deadline_seconds: float | None = None
    cancellation_requested: Callable[[], bool] | None = field(default=None, compare=False)
    fail_on_warning: bool = False
    validate_output: bool = True
    stable_mime_types: bool = False
    newline: Literal["lf", "crlf"] = "lf"
    navigation: bool = False
    navigation_depth: int = 1
    reader_theme: Literal["auto", "light", "dark"] = "auto"
    reader_max_width: str = "72ch"
    reader_font_family: str = "Georgia, serif"
    spine_range: tuple[int | None, int | None] | None = None
    exclude_content: frozenset[str] = field(default_factory=frozenset[str])
    preserve_internal_css: bool = False
    svg_policy: Literal["omit", "extract", "preserve"] = "omit"
    mathml_policy: Literal["omit", "preserve"] = "omit"
    media_policy: Literal["omit", "extract", "preserve"] = "omit"
    font_policy: Literal["omit", "extract", "preserve"] = "omit"
    css_vars: tuple[tuple[str, str], ...] = ()
    preserve_scripts: bool = False
    preserve_media_overlays: bool = False
    landmarks: bool = False
    page_list: bool = False
    resolve_switch: bool = True

    @classmethod
    def from_args(cls, args: Any, output_path: Path, css: str | None = None) -> ConversionOptions:
        """Build conversion policy from the CLI namespace in one testable seam."""
        limits = ArchiveLimits(
            args.max_archive_entries,
            args.max_compressed_bytes,
            args.max_expanded_bytes,
            args.max_entry_bytes,
            args.max_compression_ratio,
            args.max_documents,
            args.max_images,
            args.max_output_bytes,
        )
        start_end = args.spine_range.split(":", 1) if args.spine_range else None
        spine_range = None
        if start_end:
            start = int(start_end[0]) if start_end[0] else None
            end = int(start_end[1]) if start_end[1] else None
            spine_range = (start, end)
        return cls(
            input_path=args.epub_path,
            output_path=output_path,
            image_strategy=args.strategy,
            wrap_html=args.wrap
            or bool(css)
            or args.navigation
            or args.reader_max_width is not None
            or args.reader_font_family is not None,
            css=css,
            remove_toc=args.remove_toc,
            remove_cover=args.remove_cover,
            images_dir_name=args.images_dir_name,
            chunked=args.chunked,
            safe_html=args.safe_mode,
            force=args.force,
            archive_limits=limits,
            deadline_seconds=args.deadline_seconds,
            fail_on_warning=args.fail_on_warning,
            validate_output=not args.no_validate_output,
            stable_mime_types=args.stable_mime_types,
            newline=args.newline,
            navigation=args.navigation,
            navigation_depth=args.navigation_depth,
            reader_theme=args.reader_theme,
            reader_max_width=args.reader_max_width or "72ch",
            reader_font_family=args.reader_font_family or "Georgia, serif",
            spine_range=spine_range,
            exclude_content=frozenset(args.exclude_content),
            preserve_internal_css=args.preserve_internal_css,
            svg_policy=args.svg_policy,
            mathml_policy=args.mathml_policy,
            media_policy=args.media_policy,
            font_policy=args.font_policy,
            css_vars=args.css_vars,
            preserve_scripts=args.preserve_scripts,
            preserve_media_overlays=args.preserve_media_overlays,
            landmarks=args.landmarks,
            page_list=args.page_list,
            resolve_switch=not args.no_resolve_switch,
        )

    def validate(self) -> None:
        self.archive_limits.validate()
        if self.image_strategy not in {"embed", "extract"}:
            raise ValueError("image_strategy must be 'embed' or 'extract'")
        if not self.images_dir_name or self.images_dir_name in {".", ".."}:
            raise ValueError("images_dir_name must be a non-empty directory basename")
        if "{" in self.images_dir_name.replace("{stem}", "") or "}" in self.images_dir_name.replace(
            "{stem}", ""
        ):
            raise ValueError("images_dir_name may use only the {stem} placeholder")
        expanded = self.images_dir_name.format(stem=self.output_path.stem)
        if Path(expanded).name != expanded or Path(expanded).is_absolute():
            raise ValueError("images_dir_name must be a safe directory basename")
        if expanded.rstrip(". ").lower() in WINDOWS_RESERVED_NAMES:
            raise ValueError("images_dir_name must not use a Windows reserved device name")
        if self.image_strategy == "extract" and expanded == self.output_path.name:
            raise ValueError("images_dir_name cannot equal the output HTML filename")
        if self.deadline_seconds is not None and self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be greater than zero")
        if self.newline not in {"lf", "crlf"}:
            raise ValueError("newline must be 'lf' or 'crlf'")
        if not self.reader_max_width.strip() or not self.reader_font_family.strip():
            raise ValueError("reader presentation values cannot be empty")
        if self.navigation_depth < 1 or self.navigation_depth > 6:
            raise ValueError("navigation_depth must be between one and six")
        if self.reader_theme not in {"auto", "light", "dark"}:
            raise ValueError("reader_theme must be 'auto', 'light', or 'dark'")
        if self.spine_range:
            start, end = self.spine_range
            if start is not None and start < 1:
                raise ValueError("spine range start must be at least one")
            if end is not None and end < 1:
                raise ValueError("spine range end must be at least one")
            if start is not None and end is not None and start > end:
                raise ValueError("spine range start must not exceed end")
        unknown = self.exclude_content - {
            "cover",
            "navigation",
            "front-matter",
            "endnotes",
            "appendices",
        }
        if unknown:
            raise ValueError(f"Unsupported content selector(s): {', '.join(sorted(unknown))}")
        for name, policy, allowed in (
            ("svg_policy", self.svg_policy, {"omit", "extract", "preserve"}),
            ("mathml_policy", self.mathml_policy, {"omit", "preserve"}),
            ("media_policy", self.media_policy, {"omit", "extract", "preserve"}),
            ("font_policy", self.font_policy, {"omit", "extract", "preserve"}),
        ):
            if policy not in allowed:
                raise ValueError(f"{name} has an unsupported value")


@dataclass(frozen=True)
class ConversionWarning:
    """Machine-readable non-fatal diagnostic emitted during conversion."""

    code: str
    message: str
    location: str | None = None


@dataclass(frozen=True)
class ConversionResult:
    """Structured outcome available to API and CLI callers."""

    output_path: Path
    images_path: Path | None
    documents_processed: int
    images_processed: int
    skipped_images: int
    skipped_documents: int
    decode_fallbacks: int
    warnings: tuple[ConversionWarning, ...]
    duration_seconds: float
    chunked: bool
    safe_html: bool
    input_bytes: int = 0
    output_bytes: int = 0
    peak_memory_bytes: int | None = None
    chapters: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchItemResult:
    """The independently recorded outcome of one batch input."""

    input_path: Path
    result: ConversionResult | None = None
    error: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class BatchResult:
    """Aggregate batch result that preserves successful and failed books."""

    items: tuple[BatchItemResult, ...]

    @property
    def succeeded(self) -> int:
        return sum(item.result is not None for item in self.items)

    @property
    def failed(self) -> int:
        return len(self.items) - self.succeeded


class WarningCollector:
    """Collect diagnostics without coupling core conversion to terminal logging."""

    def __init__(self) -> None:
        self._warnings: list[ConversionWarning] = []
        self.started_at = monotonic()

    def add(self, code: str, message: str, location: str | None = None) -> None:
        self._warnings.append(ConversionWarning(code, message, location))

    @property
    def warnings(self) -> tuple[ConversionWarning, ...]:
        return tuple(self._warnings)

    @property
    def duration_seconds(self) -> float:
        return monotonic() - self.started_at
