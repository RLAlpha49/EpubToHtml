"""Document decoding and one-pass EPUB-to-HTML transformations."""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from ebooklib import epub

from images import ImageIndex, normalize_epub_path, resolve_epub_path
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


def stable_anchor(value: str) -> str:
    """Keep a readable anchor prefix while preventing Unicode slug collisions."""
    return f"{anchor_component(value)}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:10]}"


def decode_document(item: epub.EpubItem) -> tuple[str, ConversionWarning | None]:
    """Decode once, preferring UTF-8 then a deterministic inspectable fallback."""
    content = item.get_content()
    try:
        return content.decode("utf-8"), None
    except UnicodeDecodeError:
        try:
            import chardet

            detected = chardet.detect(content[:65_536])
            encoding = detected.get("encoding") if detected.get("confidence", 0) >= 0.5 else None
        except ImportError:
            encoding = None
        encoding = encoding or "latin-1"
        return content.decode(encoding, errors="replace"), ConversionWarning(
            "decode-fallback",
            f"Decoded document using {encoding} after UTF-8 failed (sampled up to 65536 bytes).",
            item.get_name(),
        )


def build_targets(documents: Sequence[tuple[NamedDocument, str]]) -> dict[str, DocumentTarget]:
    """Allocate all targets before rewriting forward-facing internal links."""
    targets: dict[str, DocumentTarget] = {}
    used_anchors: set[str] = set()
    for item, content in documents:
        path = normalize_epub_path(item.get_name())
        base = f"epub-{stable_anchor(path)}"
        anchor, suffix = base, 2
        while anchor in used_anchors:
            anchor, suffix = f"{base}-{suffix}", suffix + 1
        used_anchors.add(anchor)
        ids: dict[str, str] = {}
        used_ids: set[str] = set()
        for tag in BeautifulSoup(content, "html.parser").find_all(id=True):
            original = str(tag["id"])
            candidate, count = f"{anchor}--{stable_anchor(original)}", 2
            while candidate in used_ids:
                candidate, count = f"{anchor}--{stable_anchor(original)}-{count}", count + 1
            used_ids.add(candidate)
            ids.setdefault(original, candidate)
        targets[path] = DocumentTarget(anchor, ids)
    return targets


def remove_marked_content(
    soup: BeautifulSoup,
    remove_toc: bool,
    remove_cover: bool,
    excluded: frozenset[str] = frozenset(),
) -> None:
    """Filter explicitly selected EPUB semantic sections within a source document."""
    for tag in soup.find_all(["nav", "div", "section", "article"]):
        class_value = tag.get("class")
        classes: set[str] = (
            {str(value).lower() for value in class_value}
            if isinstance(class_value, list)
            else set()
        )
        epub_types = set(str(tag.get("epub:type", "")).split())
        markers: set[str] = classes | epub_types
        selected = (
            (remove_toc and "toc" in markers)
            or (remove_cover and "cover" in markers)
            or ("navigation" in excluded and bool({"toc", "landmarks", "nav"} & markers))
            or (
                "front-matter" in excluded
                and bool({"frontmatter", "front-matter", "titlepage"} & markers)
            )
            or ("endnotes" in excluded and bool({"endnotes", "endnote", "footnotes"} & markers))
            or ("appendices" in excluded and bool({"appendix", "appendices"} & markers))
            or ("cover" in excluded and "cover" in markers)
        )
        if selected:
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


def sanitize(soup: BeautifulSoup) -> int:
    """Remove active markup, event handlers, styles, and unsafe references."""
    removed = 0
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
        removed += 1
    for tag in soup.find_all("math"):
        tag.decompose()
        removed += 1
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
                removed += 1
    return removed


def rewrite_images(
    soup: BeautifulSoup, source_path: str, images: ImageIndex
) -> list[ConversionWarning]:
    """Rewrite image resources using indexed exact matching and safe fallback."""
    warnings: list[ConversionWarning] = []
    for tag_name, attributes in (
        ("img", ("src",)),
        ("image", ("href", "xlink:href")),
        ("source", ("src",)),
        ("audio", ("src",)),
        ("video", ("src", "poster")),
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


def rewrite_css_urls(css: str, source_path: str, images: ImageIndex) -> str:
    """Rewrite resolvable local stylesheet URL values to registered asset references."""

    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip().strip("'\"")
        replacement, _warning = images.resolve(source_path, raw)
        return f"url({replacement})" if replacement else match.group(0)

    return re.sub(r"url\(([^)]*)\)", replace, css, flags=re.IGNORECASE)


def prepare_document(
    item: NamedDocument,
    content: str,
    targets: dict[str, DocumentTarget],
    images: ImageIndex,
    remove_toc: bool,
    remove_cover: bool,
    safe_html: bool,
    excluded: frozenset[str] = frozenset(),
    svg_policy: str = "omit",
    mathml_policy: str = "omit",
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
            destination = path if not parsed.path else resolve_epub_path(path, str(link["href"]))
            if destination and (destination_target := targets.get(destination)):
                link["href"] = (
                    f"#{destination_target.ids.get(unquote(parsed.fragment), destination_target.anchor)}"
                )
    warnings = rewrite_images(soup, path, images)
    remove_marked_content(soup, remove_toc, remove_cover, excluded)
    if svg_policy == "omit" or safe_html:
        for tag in soup.find_all("svg"):
            tag.decompose()
    if mathml_policy == "omit":
        for tag in soup.find_all("math"):
            tag.decompose()
    if safe_html or svg_policy == "omit":
        for tag in soup.find_all(["audio", "video"]):
            tag.decompose()
    if safe_html:
        removed = sanitize(soup)
        if removed:
            warnings.append(
                ConversionWarning(
                    "unsafe-content-removed",
                    f"Safe mode removed {removed} active or unsafe markup item(s).",
                    path,
                )
            )
    body = soup.body
    inner = "".join(str(child) for child in body.contents) if body else str(soup)
    return (
        f'<section id="{target.anchor}" data-epub-source="{html.escape(path, quote=True)}">{inner}</section>',
        warnings,
    )


def wrap_html(content: str, title: str | None, css: str | None) -> str:
    """Create a standalone shell while retaining the legacy helper contract."""
    return wrap_document(content, title, css, "en", False, "72ch", "Georgia, serif")


def wrap_document(
    content: str,
    title: str | None,
    css: str | None,
    language: str,
    navigation: bool,
    max_width: str,
    font_family: str,
) -> str:
    """Wrap merged content in an accessible reading shell with opt-in navigation."""
    styles = (
        css
        or f"""
:root {{ color-scheme: light dark; }}
body {{ font-family: {font_family}; line-height: 1.6; max-width: {max_width}; margin: 0 auto; padding: clamp(1rem, 4vw, 2rem); }}
img {{ max-width: 100%; height: auto; }}
a:focus-visible {{ outline: 3px solid currentColor; outline-offset: 3px; }}
.skip-link {{ left: 1rem; position: absolute; top: -5rem; }}
.skip-link:focus {{ top: 1rem; }}
.document-navigation {{ border-block-end: 1px solid currentColor; margin-block-end: 2rem; padding-block-end: 1rem; }}
.back-to-top {{ display: block; margin-block: 2rem; }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior: auto !important; transition-duration: 0.01ms !important; }} }}
@media print {{ body {{ max-width: none; padding: 0; }} .skip-link, .document-navigation, .back-to-top {{ display: none; }} a {{ color: inherit; text-decoration: none; }} }}
"""
    )
    navigation_markup = ""
    if navigation:
        soup = BeautifulSoup(content, "html.parser")
        entries: list[str] = []
        for number, section in enumerate(soup.find_all("section", recursive=False), start=1):
            section_id = section.get("id")
            if not section_id:
                continue
            heading = section.find(re.compile(r"^h[1-6]$"))
            label = heading.get_text(" ", strip=True) if heading else f"Chapter {number}"
            entries.append(
                f'<li><a href="#{html.escape(str(section_id), quote=True)}">'
                f"{html.escape(label)}</a></li>"
            )
            section.append(
                BeautifulSoup('<a class="back-to-top" href="#top">Back to top</a>', "html.parser")
            )
        content = str(soup)
        if entries:
            navigation_markup = (
                '<nav class="document-navigation" aria-label="Table of contents"><h2>Contents</h2><ol>'
                + "".join(entries)
                + "</ol></nav>"
            )
    safe_language = language if re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", language) else "en"
    return (
        f'<!DOCTYPE html>\n<html lang="{html.escape(safe_language, quote=True)}"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{html.escape(title or 'EPUB Document', quote=True)}</title><style>{styles}</style>"
        f'</head><body id="top"><a class="skip-link" href="#main-content">Skip to content</a>{navigation_markup}'
        f'<main id="main-content" tabindex="-1">{content}</main></body></html>\n'
    )
