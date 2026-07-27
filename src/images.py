"""Image output strategies and normalized EPUB image lookup indexes."""

from __future__ import annotations

import base64
import mimetypes
import os
import posixpath
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from ebooklib import epub

from model import ConversionWarning


def normalize_epub_path(path: str) -> str:
    """Normalize a package-internal POSIX path independent of the host OS."""
    return posixpath.normpath(unquote(path).replace("\\", "/")).removeprefix("./")


def resolve_epub_path(document_path: str, reference: str) -> str | None:
    """Resolve an inert EPUB-local URI path; queries and fragments never affect lookup."""
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
        return None
    return normalize_epub_path(
        posixpath.join(posixpath.dirname(normalize_epub_path(document_path)), parsed.path)
    )


@dataclass(frozen=True)
class ImageReference:
    """The source item and its HTML replacement URL."""

    source_name: str
    url: str


class ImageOutput(ABC):
    """A focused output strategy for EPUB image resources."""

    @abstractmethod
    def register(self, item: epub.EpubItem) -> ImageReference: ...

    @staticmethod
    def media_type_for(item: epub.EpubItem, stable_mime_types: bool = False) -> str | None:
        """Determine a stable web media type from manifest metadata or common extensions."""
        if item.media_type:
            return item.media_type
        known_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        known = known_types.get(Path(item.get_name()).suffix.lower())
        return known if stable_mime_types else known or mimetypes.guess_type(item.get_name())[0]


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
        resolved = resolve_epub_path(document_path, url)
        if resolved is None:
            return None, None
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


class EmbeddedImageOutput(ImageOutput):
    """Register images as self-contained data URLs."""

    def __init__(self, safe: bool = False, stable_mime_types: bool = False) -> None:
        self.safe = safe
        self.stable_mime_types = stable_mime_types

    def register(self, item: epub.EpubItem) -> ImageReference:
        media_type = self.media_type_for(item, self.stable_mime_types)
        if not media_type:
            raise ValueError(f"Cannot determine media type for image {item.get_name()!r}")
        content = item.get_content()
        if self.safe and not supported_raster_image(media_type, content):
            raise ValueError(f"Unsupported or invalid safe-mode image: {item.get_name()!r}")
        encoded = base64.b64encode(content).decode("ascii")
        return ImageReference(item.get_name(), f"data:{media_type};base64,{encoded}")


class ExtractedImageOutput(ImageOutput):
    """Register images in a private staging directory using collision-safe names."""

    def __init__(self, directory: Path, safe: bool = False) -> None:
        self.directory = directory
        self._used_names: set[str] = set()
        self.safe = safe

    def register(self, item: epub.EpubItem) -> ImageReference:
        media_type = self.media_type_for(item)
        content = item.get_content()
        if self.safe and (not media_type or not supported_raster_image(media_type, content)):
            raise ValueError(f"Unsupported or invalid safe-mode image: {item.get_name()!r}")
        original = Path(item.get_name()).name
        stem, suffix = Path(original).stem or "image", Path(original).suffix or ".jpg"
        candidate, count = f"{stem}{suffix}", 1
        while candidate in self._used_names or (self.directory / candidate).exists():
            count += 1
            candidate = f"{stem}_{count}{suffix}"
        self._used_names.add(candidate)
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / candidate).open("xb") as output:
            output.write(content)
        # Set consistent read permissions for extracted files.
        os.chmod(self.directory / candidate, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        return ImageReference(
            item.get_name(),
            "/".join(quote(part, safe="") for part in (self.directory.name, candidate)),
        )


def supported_raster_image(media_type: str, content: bytes) -> bool:
    """Accept only common inert raster formats whose signatures match their MIME type."""
    match media_type.lower():
        case "image/png":
            return content.startswith(b"\x89PNG\r\n\x1a\n")
        case "image/jpeg":
            return content.startswith(b"\xff\xd8\xff")
        case "image/gif":
            return content.startswith((b"GIF87a", b"GIF89a"))
        case "image/webp":
            return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        case _:
            return False
