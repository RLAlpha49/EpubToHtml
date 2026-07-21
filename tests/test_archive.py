import zipfile
from pathlib import Path

import pytest

from converter import preflight_archive
from model import ArchiveLimits, ConversionOptions, InvalidEpubError


def test_preflight_rejects_archive_without_required_epub_members(tmp_path: Path) -> None:
    source = tmp_path / "invalid.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("chapter.xhtml", "<p>chapter</p>")
    options = ConversionOptions(source, tmp_path / "output.html")

    with pytest.raises(InvalidEpubError, match="missing required"):
        preflight_archive(source, options)


def test_preflight_rejects_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", "container")
        archive.writestr("../escape", "bad")
    options = ConversionOptions(source, tmp_path / "output.html", archive_limits=ArchiveLimits())

    with pytest.raises(InvalidEpubError, match="unsafe member"):
        preflight_archive(source, options)
