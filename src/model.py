"""Public conversion policy, result, diagnostics, and domain errors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Literal, Protocol

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
