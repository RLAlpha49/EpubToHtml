"""Image output strategies and normalized EPUB image lookup indexes."""

from __future__ import annotations

import base64
import mimetypes
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote, urlsplit

from ebooklib import epub

from model import ConversionWarning


def normalize_epub_path(path: str) -> str:
    """Normalize a package-internal POSIX path independent of the host OS."""
    return posixpath.normpath(unquote(path).replace("\\", "/")).removeprefix("./")


@dataclass(frozen=True)
class ImageReference:
    """The source item and its HTML replacement URL."""

    source_name: str
    url: str


class ImageOutput(Protocol):
    """A focused output strategy for EPUB image resources."""

    def register(self, item: epub.EpubItem) -> ImageReference: ...


class ImageIndex:
    """O(1)-average exact lookup with deliberately guarded basename fallback."""

    def __init__(self) -> None:
        self._full_paths: dict[str, str] = {}
        self._basenames: dict[str, list[ImageReference]] = {}

    def add(self, reference: ImageReference) -> None:
        normalized = normalize_epub_path(reference.source_name)
        self._full_paths[normalized] = reference.url
        self._basenames.setdefault(posixpath.basename(normalized).lower(), []).append(reference)

    def resolve(self, document_path: str, url: str) -> tuple[str | None, ConversionWarning | None]:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
            return None, None
        source = normalize_epub_path(document_path)
        resolved = normalize_epub_path(posixpath.join(posixpath.dirname(source), parsed.path))
        if replacement := self._full_paths.get(resolved):
            return replacement, None
        if replacement := self._full_paths.get(normalize_epub_path(parsed.path)):
            return replacement, None
        candidates = self._basenames.get(posixpath.basename(resolved).lower(), [])
        if len(candidates) == 1:
            return candidates[0].url, None
        if len(candidates) > 1:
            return None, ConversionWarning(
                "ambiguous-image",
                f"Image reference {url!r} matches multiple EPUB assets.",
                document_path,
            )
        return None, None


def media_type_for(item: epub.EpubItem) -> str | None:
    """Determine a stable web media type from manifest metadata or common extensions."""
    if item.media_type:
        return item.media_type
    return mimetypes.guess_type(item.get_name())[0] or {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(Path(item.get_name()).suffix.lower())


class EmbeddedImageOutput:
    """Register images as self-contained data URLs."""

    def register(self, item: epub.EpubItem) -> ImageReference:
        media_type = media_type_for(item)
        if not media_type:
            raise ValueError(f"Cannot determine media type for image {item.get_name()!r}")
        encoded = base64.b64encode(item.get_content()).decode("ascii")
        return ImageReference(item.get_name(), f"data:{media_type};base64,{encoded}")


class ExtractedImageOutput:
    """Register images in a private staging directory using collision-safe names."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._used_names: set[str] = set()

    def register(self, item: epub.EpubItem) -> ImageReference:
        original = Path(item.get_name()).name
        stem, suffix = Path(original).stem or "image", Path(original).suffix or ".jpg"
        candidate, count = f"{stem}{suffix}", 1
        while candidate in self._used_names or (self.directory / candidate).exists():
            count += 1
            candidate = f"{stem}_{count}{suffix}"
        self._used_names.add(candidate)
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / candidate).open("xb") as output:
            output.write(item.get_content())
        return ImageReference(
            item.get_name(),
            "/".join(quote(part, safe="") for part in (self.directory.name, candidate)),
        )
