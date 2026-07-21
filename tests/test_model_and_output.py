from pathlib import Path

import pytest

from model import ConversionOptions, OutputError
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
