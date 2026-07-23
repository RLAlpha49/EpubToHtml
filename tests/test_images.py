from images import (
    ImageIndex,
    ImageReference,
    normalize_epub_path,
    resolve_epub_path,
    supported_raster_image,
)


def test_normalizes_and_resolves_document_relative_image_paths() -> None:
    index = ImageIndex()
    index.add(ImageReference("images/cover art.png", "data:image/png;base64,AA=="))

    replacement, warning = index.resolve("text/chapter.xhtml", "../images/cover%20art.png")

    assert replacement == "data:image/png;base64,AA=="
    assert warning is None
    assert normalize_epub_path("./images\\cover%20art.png") == "images/cover art.png"


def test_ambiguous_image_basename_is_never_guessed() -> None:
    index = ImageIndex()
    index.add(ImageReference("one/photo.jpg", "one"))
    index.add(ImageReference("two/photo.jpg", "two"))

    replacement, warning = index.resolve("text/chapter.xhtml", "photo.jpg")

    assert replacement is None
    assert warning and warning.code == "ambiguous-image"


def test_path_resolution_ignores_query_and_fragment_but_rejects_external_paths() -> None:
    assert (
        resolve_epub_path("text/chapter.xhtml", "../images/a.png?size=2#preview") == "images/a.png"
    )
    assert resolve_epub_path("text/chapter.xhtml", "/images/a.png") is None
    assert resolve_epub_path("text/chapter.xhtml", "https://example.test/a.png") is None


def test_safe_image_signatures_reject_svg_and_mismatched_content() -> None:
    assert supported_raster_image("image/png", b"\x89PNG\r\n\x1a\ncontent")
    assert not supported_raster_image("image/png", b"not a png")
    assert not supported_raster_image("image/svg+xml", b"<svg/>")
