from pathlib import Path

import pytest

from converter import _check_cancelled, _validate_staged_html
from model import ConversionCancelledError, ConversionOptions, OutputError, OutputValidationError
from output import StagedOutput


def test_options_reject_unsafe_image_directory_names(tmp_path: Path) -> None:
    options = ConversionOptions(
        tmp_path / "book.epub", tmp_path / "out.html", images_dir_name="../assets"
    )

    with pytest.raises(ValueError, match="safe directory basename"):
        options.validate()


@pytest.mark.parametrize("name", ["CON", "lpt1", "out.html"])
def test_options_reject_reserved_or_colliding_image_directory_names(
    tmp_path: Path, name: str
) -> None:
    options = ConversionOptions(
        tmp_path / "book.epub",
        tmp_path / "out.html",
        image_strategy="extract",
        images_dir_name=name,
    )

    with pytest.raises(ValueError):
        options.validate()


def test_staged_output_preserves_existing_file_without_force(tmp_path: Path) -> None:
    output = tmp_path / "out.html"
    output.write_text("original", encoding="utf-8")

    with (
        pytest.raises(OutputError, match="already exists"),
        StagedOutput(output, None, force=False),
    ):
        pass

    assert output.read_text(encoding="utf-8") == "original"


def test_staged_output_commits_new_content(tmp_path: Path) -> None:
    output = tmp_path / "out.html"

    with StagedOutput(output, None, force=False) as staged:
        with staged.open_html() as handle:
            handle.write("converted")
        staged.commit()

    assert output.read_text(encoding="utf-8") == "converted"


def test_staged_output_supports_explicit_crlf_newlines(tmp_path: Path) -> None:
    output = tmp_path / "out.html"

    with StagedOutput(output, None, force=False) as staged:
        with staged.open_html("\r\n") as handle:
            handle.write("one\ntwo\n")
        staged.commit()

    assert output.read_bytes() == b"one\r\ntwo\r\n"


def test_options_reject_non_positive_deadline(tmp_path: Path) -> None:
    options = ConversionOptions(tmp_path / "book.epub", tmp_path / "out.html", deadline_seconds=0)

    with pytest.raises(ValueError, match="deadline_seconds"):
        options.validate()


def test_cancellation_callback_stops_conversion_before_work(tmp_path: Path) -> None:
    options = ConversionOptions(
        tmp_path / "book.epub", tmp_path / "out.html", cancellation_requested=lambda: True
    )

    with pytest.raises(ConversionCancelledError, match="cancelled"):
        _check_cancelled(options, 0)


def test_staged_validation_rejects_duplicate_ids_and_broken_local_links(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.html"
    duplicate.write_text('<p id="same"></p><p id="same"></p>', encoding="utf-8")
    broken = tmp_path / "broken.html"
    broken.write_text('<a href="#missing">missing</a>', encoding="utf-8")
    resource = tmp_path / "resource.html"
    resource.write_text('<img src="missing.png">', encoding="utf-8")

    with pytest.raises(OutputValidationError, match="duplicate"):
        _validate_staged_html(duplicate)
    with pytest.raises(OutputValidationError, match="unresolved"):
        _validate_staged_html(broken)
    with pytest.raises(OutputValidationError, match="unresolved local resource"):
        _validate_staged_html(resource)
