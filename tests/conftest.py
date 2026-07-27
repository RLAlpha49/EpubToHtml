"""Shared test fixtures and EPUB builder for integration tests."""

from __future__ import annotations

import base64
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# A minimal 1x1 transparent PNG (67 bytes) for image-related tests.
MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# A minimal 1x1 JPEG (not a real JPEG, just enough for signature checks).
MINIMAL_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb"
    b"\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b"
    b"\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \"\x1c"
    b"CC\x1eF\x1c\x1c\x1e\x1c\xff\xd9"
)


def _chapter_html(title: str, body: str) -> str:
    """Build a minimal XHTML chapter document."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        f"<head><title>{title}</title></head>"
        f"<body><h1>{title}</h1>{body}</body>"
        "</html>"
    )


def _nav_html(chapters: list[tuple[str, str]]) -> str:
    """Build a minimal EPUB 3 navigation document with a TOC."""
    items = "".join(
        f'<li><a href="chapter_{i + 1}.xhtml">{title}</a></li>'
        for i, (title, _) in enumerate(chapters)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        "<head><title>Table of Contents</title></head>"
        f'<body><nav epub:type="toc"><ol>{items}</ol></nav></body>'
        "</html>"
    )


def build_epub(
    path: Path,
    title: str = "Test Book",
    author: str = "Test Author",
    language: str = "en",
    chapters: list[tuple[str, str]] | None = None,
    images: list[tuple[str, bytes, str]] | None = None,
    css: str | None = None,
    toc: bool = True,
    include_nav: bool = True,
    metadata: dict[str, str] | None = None,
) -> Path:
    """Build a minimal but valid EPUB file at *path*.

    All ZIP members are stored with DEFLATE compression so that the
    ``preflight_archive`` compression-ratio check accepts the archive
    (the ``mimetype`` file is normally stored uncompressed per the EPUB
    spec, but the preflight policy rejects uncompressed members with
    content).
    """
    if chapters is None:
        chapters = [("Chapter 1", "<p>Hello, world!</p>")]

    manifest: list[str] = []
    spine: list[str] = []

    if include_nav and toc:
        manifest.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
        spine.append('<itemref idref="nav"/>')

    for i, (_chapter_title, _) in enumerate(chapters):
        item_id = f"chapter_{i + 1}"
        manifest.append(
            f'<item id="{item_id}" href="{item_id}.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{item_id}"/>')

    if images:
        for i, (name, _, media_type) in enumerate(images):
            item_id = f"image_{i + 1}"
            manifest.append(
                f'<item id="{item_id}" href="images/{name}" media-type="{media_type}"/>'
            )

    if css:
        manifest.append('<item id="style" href="style.css" media-type="text/css"/>')

    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">urn:uuid:test-{title.replace(" ", "").lower()}</dc:identifier>\n'
        f"    <dc:title>{title}</dc:title>\n"
        f"    <dc:creator>{author}</dc:creator>\n"
        f"    <dc:language>{language}</dc:language>\n"
        + (
            "".join(
                f"    <dc:{key}>{value}</dc:{key}>\n" for key, value in (metadata or {}).items()
            )
        )
        + '    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n" + "\n".join(f"    {m}" for m in manifest) + "\n  </manifest>\n"
        "  <spine>\n" + "\n".join(f"    {s}" for s in spine) + "\n  </spine>\n"
        "</package>"
    )

    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("content.opf", opf)

        if include_nav and toc:
            archive.writestr("nav.xhtml", _nav_html(chapters))

        for i, (chapter_title, content) in enumerate(chapters):
            archive.writestr(f"chapter_{i + 1}.xhtml", _chapter_html(chapter_title, content))

        if images:
            for _i, (name, data, _) in enumerate(images):
                archive.writestr(f"images/{name}", data)

        if css:
            archive.writestr("style.css", css)

    return path


@pytest.fixture
def epub_builder(tmp_path: Path) -> Callable[..., Path]:
    """Return a function that builds EPUB files in a temporary directory."""

    def _build(**kwargs: Any) -> Path:
        name = kwargs.pop("name", "test.epub")
        path = tmp_path / name
        return build_epub(path, **kwargs)

    return _build
