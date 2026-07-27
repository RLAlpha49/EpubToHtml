"""End-to-end integration tests that convert real EPUB files and verify output.

These tests build minimal but valid EPUB archives (using ``zipfile`` directly
so that all members are DEFLATE-compressed, satisfying the preflight policy)
and exercise the full ``convert()`` pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import MINIMAL_PNG
from converter import convert
from model import ConversionOptions


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Basic conversion
# ---------------------------------------------------------------------------


def test_convert_minimal_epub_produces_html(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder()
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    assert result.output_path == output
    assert output.exists()
    content = _read(output)
    assert "<html" in content
    assert "Hello, world!" in content
    assert result.documents_processed >= 1


def test_convert_unwrapped_epub_emits_plain_sections(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(chapters=[("Ch 1", "<p>First</p>"), ("Ch 2", "<p>Second</p>")])
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output))

    assert output.exists()
    content = _read(output)
    assert "First" in content
    assert "Second" in content
    assert "<section" in content
    assert result.documents_processed >= 2


# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------


def test_convert_embeds_images_as_data_urls(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", '<img src="images/test.png" alt="pic">')],
        images=[("test.png", MINIMAL_PNG, "image/png")],
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert "data:image/png;base64," in content
    assert result.images_processed == 1
    assert result.skipped_images == 0


def test_convert_extracts_images_to_directory(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", '<img src="images/test.png" alt="pic">')],
        images=[("test.png", MINIMAL_PNG, "image/png")],
    )
    output = tmp_path / "out.html"

    result = convert(
        ConversionOptions(
            epub_path,
            output,
            image_strategy="extract",
            wrap_html=True,
            validate_output=False,
        )
    )

    assert result.images_path is not None
    assert result.images_path.exists()
    assert (result.images_path / "test.png").exists()
    content = _read(output)
    # Extracted images use a relative path derived from the output filename.
    assert "test.png" in content


def test_convert_preserves_srcset_in_embedded_images(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[
            (
                "Ch 1",
                '<img src="images/test.png" srcset="images/test.png 1x, images/test.png 2x">',
            )
        ],
        images=[("test.png", MINIMAL_PNG, "image/png")],
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert "data:image/png;base64," in content
    assert "1x" in content
    assert "2x" in content
    assert result.images_processed == 1


# ---------------------------------------------------------------------------
# Navigation and wrapping
# ---------------------------------------------------------------------------


def test_convert_generates_navigation_toc(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Intro", "<p>Intro</p>"), ("Body", "<p>Body</p>")],
        toc=True,
    )
    output = tmp_path / "out.html"

    result = convert(
        ConversionOptions(epub_path, output, wrap_html=True, navigation=True, remove_toc=True)
    )

    content = _read(output)
    assert 'aria-label="Table of contents"' in content
    assert "Intro" in content
    assert "Body" in content


def test_convert_wrap_html_includes_title_and_language(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(title="My Novel", language="fr")
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert "<title>My Novel</title>" in content
    assert 'lang="fr"' in content


def test_convert_wrap_html_includes_epub_metadata(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        title="Metadata Book",
        author="Jane Doe",
        metadata={
            "publisher": "Acme Press",
            "date": "2024-06-01",
            "rights": "CC BY-SA 4.0",
            "description": "A book about metadata.",
            "subject": "Testing",
        },
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert '<meta name="author" content="Jane Doe">' in content
    assert '<meta name="publisher" content="Acme Press">' in content
    assert '<meta name="dcterms.date" content="2024-06-01">' in content
    assert '<meta name="dcterms.rights" content="CC BY-SA 4.0">' in content
    assert '<meta name="description" content="A book about metadata.">' in content
    assert '<meta name="keywords" content="Testing">' in content


def test_convert_chunked_wrap_html_includes_epub_metadata(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        title="Chunked Metadata Book",
        author="John Smith",
        metadata={"publisher": "Beta Publishing", "rights": "All rights reserved"},
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True, chunked=True))

    content = _read(output)
    assert '<meta name="author" content="John Smith">' in content
    assert '<meta name="publisher" content="Beta Publishing">' in content
    assert '<meta name="dcterms.rights" content="All rights reserved">' in content


def test_convert_wrap_html_without_metadata_omits_meta_tags(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder()
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert '<meta name="publisher"' not in content
    assert '<meta name="dcterms.rights"' not in content


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


def test_convert_inlines_internal_css(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", "<p>styled</p>")],
        css=".highlight { color: red; }",
    )
    output = tmp_path / "out.html"

    result = convert(
        ConversionOptions(epub_path, output, wrap_html=True, preserve_internal_css=True)
    )

    content = _read(output)
    assert ".highlight" in content
    assert "color: red" in content


# ---------------------------------------------------------------------------
# Content filtering
# ---------------------------------------------------------------------------


def test_convert_removes_svg_by_default(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", "<p>keep</p><svg><rect/></svg>")],
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert "keep" in content
    assert "<svg" not in content


def test_convert_removes_mathml_by_default(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", "<p>keep</p><math><mi>x</mi></math>")],
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert "keep" in content
    assert "<math" not in content


def test_convert_safe_mode_strips_active_content(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[
            (
                "Ch 1",
                '<p>safe</p><script>alert(1)</script>'
                '<img onerror="evil()" src="images/test.png">',
            )
        ],
        images=[("test.png", MINIMAL_PNG, "image/png")],
    )
    output = tmp_path / "out.html"

    result = convert(
        ConversionOptions(epub_path, output, wrap_html=True, safe_html=True)
    )

    content = _read(output)
    assert "safe" in content
    assert "<script" not in content
    assert "onerror" not in content
    assert result.warnings  # at least one warning about removed content


def test_convert_excludes_appendices(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[
            ("Main", "<p>main content</p>"),
            ("Appendix", '<section epub:type="appendix"><p>appendix</p></section>'),
        ],
    )
    output = tmp_path / "out.html"

    result = convert(
        ConversionOptions(
            epub_path,
            output,
            wrap_html=True,
            remove_toc=True,
            exclude_content=frozenset({"appendices"}),
        )
    )

    content = _read(output)
    assert "main content" in content
    # The appendix section content should be removed.
    assert 'epub:type="appendix"' not in content
    assert "<p>appendix</p>" not in content


# ---------------------------------------------------------------------------
# Spine range
# ---------------------------------------------------------------------------


def test_convert_spine_range_limits_documents(tmp_path: Path, epub_builder) -> None:
    # toc=False so the nav item doesn't occupy a spine slot.
    epub_path = epub_builder(
        chapters=[
            ("Ch 1", "<p>alpha</p>"),
            ("Ch 2", "<p>two</p>"),
            ("Ch 3", "<p>three</p>"),
            ("Ch 4", "<p>omega</p>"),
        ],
        toc=False,
    )
    output = tmp_path / "out.html"

    result = convert(
        ConversionOptions(epub_path, output, wrap_html=True, spine_range=(2, 3))
    )

    content = _read(output)
    assert "<p>two</p>" in content
    assert "<p>three</p>" in content
    assert "<p>alpha</p>" not in content
    assert "<p>omega</p>" not in content


# ---------------------------------------------------------------------------
# Chunked output
# ---------------------------------------------------------------------------


def test_convert_chunked_output_streams_sections(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", "<p>one</p>"), ("Ch 2", "<p>two</p>")],
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, chunked=True, wrap_html=True))

    assert output.exists()
    content = _read(output)
    assert "one" in content
    assert "two" in content
    assert result.chunked is True


# ---------------------------------------------------------------------------
# Result metadata
# ---------------------------------------------------------------------------


def test_convert_result_reports_input_and_output_bytes(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder()
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    assert result.input_bytes == epub_path.stat().st_size
    assert result.output_bytes == output.stat().st_size
    assert result.output_bytes > 0


def test_convert_result_reports_peak_memory(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", "<p>alpha</p>"), ("Ch 2", "<p>beta</p>")],
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    assert result.peak_memory_bytes is not None
    assert result.peak_memory_bytes > 0


def test_convert_result_chapters_list_contains_source_names(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[("Ch 1", "<p>a</p>"), ("Ch 2", "<p>b</p>")],
        toc=False,
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    assert len(result.chapters) >= 2
    assert all("chapter" in name for name in result.chapters)


# ---------------------------------------------------------------------------
# Multiple chapters with internal links
# ---------------------------------------------------------------------------


def test_convert_rewrites_internal_links_across_chapters(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder(
        chapters=[
            ("Ch 1", '<p><a href="chapter_2.xhtml">next</a></p>'),
            ("Ch 2", "<p>destination</p>"),
        ],
        toc=False,
    )
    output = tmp_path / "out.html"

    result = convert(ConversionOptions(epub_path, output, wrap_html=True))

    content = _read(output)
    assert "destination" in content
    # The cross-document link should have been rewritten to a fragment.
    assert 'href="#' in content
    # The original xhtml filename should not appear in any href attribute.
    assert 'href="chapter_2.xhtml' not in content


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_convert_rejects_nonexistent_file(tmp_path: Path) -> None:
    output = tmp_path / "out.html"

    with pytest.raises(Exception, match="not found"):
        convert(ConversionOptions(tmp_path / "missing.epub", output))


def test_convert_rejects_invalid_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip file")
    output = tmp_path / "out.html"

    with pytest.raises(Exception, match="valid ZIP"):
        convert(ConversionOptions(bad, output))


def test_convert_force_overwrites_existing_output(tmp_path: Path, epub_builder) -> None:
    epub_path = epub_builder()
    output = tmp_path / "out.html"
    output.write_text("old content", encoding="utf-8")

    result = convert(
        ConversionOptions(epub_path, output, wrap_html=True, force=True)
    )

    content = _read(output)
    assert "old content" not in content
    assert "Hello, world!" in content
