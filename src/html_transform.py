"""Document decoding and one-pass EPUB-to-HTML transformations."""

from __future__ import annotations

import html
import posixpath
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from ebooklib import epub

from images import ImageIndex, normalize_epub_path
from model import ConversionWarning


@dataclass(frozen=True)
class DocumentTarget:
    """The output targets allocated for a source EPUB document."""

    anchor: str
    ids: dict[str, str]


class NamedDocument(Protocol):
    """The minimal document interface needed after content has been decoded."""

    def get_name(self) -> str: ...


def anchor_component(value: str) -> str:
    """Create readable deterministic components for generated HTML identifiers."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "item"


def decode_document(item: epub.EpubItem) -> tuple[str, ConversionWarning | None]:
    """Decode once, preferring UTF-8 then a deterministic inspectable fallback."""
    content = item.get_content()
    try:
        return content.decode("utf-8"), None
    except UnicodeDecodeError:
        try:
            import chardet

            detected = chardet.detect(content)
            encoding = detected.get("encoding") if detected.get("confidence", 0) >= 0.5 else None
        except ImportError:
            encoding = None
        encoding = encoding or "latin-1"
        return content.decode(encoding, errors="replace"), ConversionWarning(
            "decode-fallback",
            f"Decoded document using {encoding} after UTF-8 failed.",
            item.get_name(),
        )


def build_targets(documents: list[tuple[epub.EpubItem, str]]) -> dict[str, DocumentTarget]:
    """Allocate all targets before rewriting forward-facing internal links."""
    targets: dict[str, DocumentTarget] = {}
    used_anchors: set[str] = set()
    for item, content in documents:
        path = normalize_epub_path(item.get_name())
        base = f"epub-{anchor_component(path)}"
        anchor, suffix = base, 2
        while anchor in used_anchors:
            anchor, suffix = f"{base}-{suffix}", suffix + 1
        used_anchors.add(anchor)
        ids: dict[str, str] = {}
        used_ids: set[str] = set()
        for tag in BeautifulSoup(content, "html.parser").find_all(id=True):
            original = str(tag["id"])
            candidate, count = f"{anchor}--{anchor_component(original)}", 2
            while candidate in used_ids:
                candidate, count = f"{anchor}--{anchor_component(original)}-{count}", count + 1
            used_ids.add(candidate)
            ids.setdefault(original, candidate)
        targets[path] = DocumentTarget(anchor, ids)
    return targets


def remove_marked_content(soup: BeautifulSoup, remove_toc: bool, remove_cover: bool) -> None:
    """Filter TOC/cover markers within one parsed source document."""
    for tag in soup.find_all(["nav", "div", "section", "article"]):
        class_value = tag.get("class")
        classes = (
            {str(value).lower() for value in class_value}
            if isinstance(class_value, list)
            else set()
        )
        epub_types = set(str(tag.get("epub:type", "")).split())
        if (remove_toc and ("toc" in classes or "toc" in epub_types)) or (
            remove_cover and ("cover" in classes or "cover" in epub_types)
        ):
            tag.decompose()


def safe_url(tag_name: str, attribute: str, value: str) -> bool:
    """Permit inert local links and generated raster data URLs only."""
    parsed = urlsplit(value.strip())
    if parsed.netloc:
        return False
    if tag_name == "a" and attribute == "href":
        return parsed.scheme.lower() in {"", "http", "https", "mailto", "tel"}
    return not parsed.scheme or (
        parsed.scheme.lower() == "data"
        and parsed.path.lower().startswith(("image/png", "image/jpeg", "image/gif", "image/webp"))
    )


def sanitize(soup: BeautifulSoup) -> None:
    """Remove active markup, event handlers, styles, and unsafe references."""
    for tag in soup.find_all(
        {
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
    ):
        tag.decompose()
    for tag in soup.find_all(True):
        for attribute in tuple(tag.attrs):
            name, value = str(attribute).lower(), str(tag.attrs[attribute])
            if (
                name.startswith("on")
                or name == "style"
                or (
                    name in {"href", "src", "poster", "xlink:href"}
                    and not safe_url(tag.name, name, value)
                )
            ):
                del tag.attrs[attribute]


def rewrite_images(
    soup: BeautifulSoup, source_path: str, images: ImageIndex
) -> list[ConversionWarning]:
    """Rewrite image resources using indexed exact matching and safe fallback."""
    warnings: list[ConversionWarning] = []
    for tag_name, attributes in (
        ("img", ("src",)),
        ("image", ("href", "xlink:href")),
        ("source", ("src",)),
    ):
        for tag in soup.find_all(tag_name):
            for attribute in attributes:
                if value := tag.get(attribute):
                    replacement, warning = images.resolve(source_path, str(value))
                    if replacement:
                        tag[attribute] = replacement
                    elif warning:
                        warnings.append(warning)
                    else:
                        warnings.append(
                            ConversionWarning(
                                "unresolved-image",
                                f"Could not resolve image {value!r}.",
                                source_path,
                            )
                        )
    return warnings


def prepare_document(
    item: NamedDocument,
    content: str,
    targets: dict[str, DocumentTarget],
    images: ImageIndex,
    remove_toc: bool,
    remove_cover: bool,
    safe_html: bool,
) -> tuple[str, list[ConversionWarning]]:
    """Apply all document transformations to one already-decoded document."""
    path = normalize_epub_path(item.get_name())
    target = targets[path]
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(id=True):
        if replacement := target.ids.get(str(tag["id"])):
            tag["id"] = replacement
    for link in soup.find_all("a", href=True):
        parsed = urlsplit(str(link["href"]))
        if not (parsed.scheme or parsed.netloc or parsed.query or parsed.path.startswith("/")):
            destination = (
                path
                if not parsed.path
                else normalize_epub_path(posixpath.join(posixpath.dirname(path), parsed.path))
            )
            if destination_target := targets.get(destination):
                link["href"] = (
                    f"#{destination_target.ids.get(unquote(parsed.fragment), destination_target.anchor)}"
                )
    warnings = rewrite_images(soup, path, images)
    remove_marked_content(soup, remove_toc, remove_cover)
    if safe_html:
        sanitize(soup)
    body = soup.body
    inner = "".join(str(child) for child in body.contents) if body else str(soup)
    return (
        f'<section id="{target.anchor}" data-epub-source="{html.escape(path, quote=True)}">{inner}</section>',
        warnings,
    )


def wrap_html(content: str, title: str | None, css: str | None) -> str:
    """Create a standalone shell while escaping metadata at serialization."""
    styles = (
        css
        or "body { font-family: Georgia, serif; line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 20px; } img { max-width: 100%; height: auto; }"
    )
    return f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{html.escape(title or "EPUB Document", quote=True)}</title><style>{styles}</style></head><body>{content}</body></html>\n'
