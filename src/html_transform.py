"""Document decoding and one-pass EPUB-to-HTML transformations."""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from ebooklib import epub

from images import ImageIndex, normalize_epub_path, resolve_epub_path
from model import ConversionWarning, DocumentTransformConfig


@dataclass(frozen=True)
class DocumentTarget:
    """The output targets allocated for a source EPUB document."""

    anchor: str
    ids: dict[str, str]
    soup: BeautifulSoup | None = None


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
        detected_label = encoding or "unknown"
        encoding = encoding or "latin-1"
        return content.decode(encoding, errors="replace"), ConversionWarning(
            "decode-fallback",
            f"Decoded document using {encoding} after UTF-8 failed (detected: {detected_label}, sampled up to 65536 bytes).",
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
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all(id=True):
            original = str(tag["id"])
            candidate, count = f"{anchor}--{stable_anchor(original)}", 2
            while candidate in used_ids:
                candidate, count = f"{anchor}--{stable_anchor(original)}-{count}", count + 1
            used_ids.add(candidate)
            ids.setdefault(original, candidate)
        targets[path] = DocumentTarget(anchor, ids, soup)
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
        role_types = set(str(tag.get("role", "")).split())
        data_epub_types = set(str(tag.get("data-epub-type", "")).split())
        markers: set[str] = classes | epub_types | role_types | data_epub_types
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
    if parsed.scheme.lower() == "data":
        # Extract the MIME type from data: URLs (format: data:[<mediatype>][;base64],<data>)
        # Using ; and , as delimiters ensures we match the exact mediatype, not a prefix.
        path = parsed.path
        mime = path.split(";")[0].split(",")[0].lower()
        return mime in {"image/png", "image/jpeg", "image/gif", "image/webp"}
    return not parsed.scheme


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


def _parse_srcset(value: str) -> list[tuple[str, str]]:
    """Parse a srcset attribute into (url, descriptor) pairs.

    Each comma-separated entry may have a URL followed by an optional
    width (``600w``) or pixel-density (``2x``) descriptor.
    """
    entries: list[tuple[str, str]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) == 1:
            entries.append((tokens[0], ""))
        else:
            entries.append((tokens[0], " ".join(tokens[1:])))
    return entries


def _rewrite_srcset(
    value: str, source_path: str, images: ImageIndex
) -> tuple[str, list[ConversionWarning]]:
    """Rewrite every URL inside a srcset value, preserving descriptors.

    URLs that cannot be resolved are kept verbatim so the srcset remains
    usable, and an ``unresolved-image`` warning is emitted for each.
    """
    warnings: list[ConversionWarning] = []
    rewritten: list[str] = []
    for url, descriptor in _parse_srcset(value):
        replacement, warning = images.resolve(source_path, url)
        entry = f"{url} {descriptor}" if descriptor else url
        if replacement:
            entry = f"{replacement} {descriptor}" if descriptor else replacement
        elif warning:
            warnings.append(warning)
        else:
            warnings.append(
                ConversionWarning(
                    "unresolved-image",
                    f"Could not resolve image {url!r}.",
                    source_path,
                )
            )
        rewritten.append(entry)
    return ", ".join(rewritten), warnings


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
    for tag in soup.find_all(["img", "source"]):
        if value := tag.get("srcset"):
            rewritten, srcset_warnings = _rewrite_srcset(str(value), source_path, images)
            tag["srcset"] = rewritten
            warnings.extend(srcset_warnings)
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
    config: DocumentTransformConfig | bool,
    remove_cover: bool = False,
    safe_html: bool = False,
    excluded: frozenset[str] = frozenset(),
    svg_policy: Literal["omit", "extract", "preserve"] = "omit",
    mathml_policy: Literal["omit", "preserve"] = "omit",
) -> tuple[str, list[ConversionWarning]]:
    """Apply all document transformations to one already-decoded document."""
    if isinstance(config, bool):
        config = DocumentTransformConfig(
            remove_toc=config,
            remove_cover=remove_cover,
            safe_html=safe_html,
            excluded=excluded,
            svg_policy=svg_policy,
            mathml_policy=mathml_policy,
        )
    path = normalize_epub_path(item.get_name())
    target = targets[path]
    soup = target.soup
    if soup is None:
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
    remove_marked_content(soup, config.remove_toc, config.remove_cover, config.excluded)
    if config.svg_policy == "omit" or config.safe_html:
        for tag in soup.find_all("svg"):
            tag.decompose()
    if config.mathml_policy == "omit":
        for tag in soup.find_all("math"):
            tag.decompose()
    if config.safe_html or config.svg_policy == "omit":
        for tag in soup.find_all(["audio", "video"]):
            tag.decompose()
    if config.safe_html:
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
    book: epub.EpubBook | None = None,
    theme: str = "auto",
    navigation_depth: int = 1,
) -> str:
    """Wrap merged content in an accessible reading shell with opt-in navigation."""
    theme_css = {
        "auto": ":root { color-scheme: light dark; --page-bg: Canvas; --page-fg: CanvasText; }",
        "light": ":root { color-scheme: light; --page-bg: #fff; --page-fg: #171717; }",
        "dark": ":root { color-scheme: dark; --page-bg: #171717; --page-fg: #f5f5f5; }",
    }[theme]
    default_styles = f"""
{theme_css}
body {{ background: var(--page-bg); color: var(--page-fg); font-family: {font_family}; line-height: 1.6; max-width: {max_width}; margin: 0 auto; padding: clamp(1rem, 4vw, 2rem); }}
img {{ max-width: 100%; height: auto; }}
a:focus-visible {{ outline: 3px solid currentColor; outline-offset: 3px; }}
.skip-link {{ left: 1rem; position: absolute; top: -5rem; }}
.skip-link:focus {{ top: 1rem; }}
.document-navigation {{ border-block-end: 1px solid currentColor; margin-block-end: 2rem; padding-block-end: 1rem; }}
.back-to-top {{ display: block; margin-block: 2rem; }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior: auto !important; transition-duration: 0.01ms !important; }} }}
@media print {{ body {{ max-width: none; padding: 0; }} .skip-link, .document-navigation, .back-to-top {{ display: none; }} a {{ color: inherit; text-decoration: none; }} }}
"""
    styles = f"{theme_css}\n{css}" if css else default_styles
    navigation_markup = ""
    if navigation:
        soup = BeautifulSoup(content, "html.parser")
        entries: list[str] = []
        source_nav = soup.find(
            lambda tag: tag.name == "nav" and "toc" in str(tag.get("epub:type", "")).lower().split()
        )
        if source_nav is None:
            source_nav = soup.find(
                lambda tag: tag.name == "nav" and "toc" in str(tag.get("role", "")).lower().split()
            )
        if source_nav is not None:
            for link in source_nav.find_all("a", href=True):
                href = str(link["href"])
                if href.startswith("#"):
                    destination = href
                else:
                    destination = next(
                        (
                            f"#{section.get('id')}"
                            for section in soup.find_all("section", recursive=False)
                            if re.search(
                                re.escape(href.split("#", 1)[0]) + r"$",
                                str(section.get("data-epub-source", "")),
                            )
                        ),
                        href,
                    )
                entries.append(
                    f'<li><a href="{html.escape(destination, quote=True)}">'
                    f"{html.escape(link.get_text(' ', strip=True))}</a></li>"
                )
        for number, section in enumerate(soup.find_all("section", recursive=False), start=1):
            section_id = section.get("id")
            if not section_id:
                continue
            headings = section.find_all(re.compile(r"^h[1-6]$"))
            heading = next(
                (candidate for candidate in headings if int(candidate.name[1]) <= navigation_depth),
                None,
            )
            if not entries:
                label = heading.get_text(" ", strip=True) if heading else f"Chapter {number}"
                entries.append(
                    f'<li><a href="#{html.escape(str(section_id), quote=True)}">'
                    f"{html.escape(label)}</a></li>"
                )
            if section.find("nav") is None:
                section.append(
                    BeautifulSoup(
                        '<a class="back-to-top" href="#top">Back to top</a>', "html.parser"
                    )
                )
        content = str(soup)
        if entries:
            navigation_markup = (
                '<nav class="document-navigation" aria-label="Table of contents"><h2>Contents</h2><ol>'
                + "".join(entries)
                + "</ol></nav>"
            )

    metadata_tags = _extract_epub_metadata(book) if book is not None else ""
    safe_language = language if re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", language) else "en"
    return (
        f'<!DOCTYPE html>\n<html lang="{html.escape(safe_language, quote=True)}"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{html.escape(title or 'EPUB Document', quote=True)}</title>"
        f"{metadata_tags}<style>{styles}</style>"
        f'</head><body id="top"><a class="skip-link" href="#main-content">Skip to content</a>{navigation_markup}'
        f'<main id="main-content" tabindex="-1">{content}</main></body></html>\n'
    )


def _extract_epub_metadata(book: epub.EpubBook) -> str:
    """Extract Dublin Core metadata from an EPUB and return as HTML meta tags."""
    tags: list[str] = []

    # Helper to get metadata values
    def get_meta(namespace: str, name: str) -> list[str]:
        try:
            values = book.get_metadata(namespace, name)
            result = []
            for value in values:
                if isinstance(value, tuple):
                    result.append(str(value[0]))
                else:
                    result.append(str(value))
            return result
        except (AttributeError, IndexError, TypeError):
            return []

    # Dublin Core metadata
    creators = get_meta("DC", "creator")
    for creator in creators:
        tags.append(f'<meta name="author" content="{html.escape(creator, quote=True)}">')

    publishers = get_meta("DC", "publisher")
    for publisher in publishers:
        tags.append(f'<meta name="publisher" content="{html.escape(publisher, quote=True)}">')

    dates = get_meta("DC", "date")
    for date in dates:
        tags.append(f'<meta name="dcterms.date" content="{html.escape(date, quote=True)}">')

    identifiers = get_meta("DC", "identifier")
    for identifier in identifiers:
        tags.append(
            f'<meta name="dcterms.identifier" content="{html.escape(identifier, quote=True)}">'
        )

    rights = get_meta("DC", "rights")
    for right in rights:
        tags.append(f'<meta name="dcterms.rights" content="{html.escape(right, quote=True)}">')

    descriptions = get_meta("DC", "description")
    for description in descriptions:
        tags.append(f'<meta name="description" content="{html.escape(description, quote=True)}">')

    subjects = get_meta("DC", "subject")
    for subject in subjects:
        tags.append(f'<meta name="keywords" content="{html.escape(subject, quote=True)}">')

    # Language (already in html lang attribute, but add as meta too)
    languages = get_meta("DC", "language")
    for lang in languages:
        tags.append(f'<meta name="dcterms.language" content="{html.escape(lang, quote=True)}">')

    return "\n".join(tags)
