from images import ImageIndex, ImageReference, normalize_epub_path


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
