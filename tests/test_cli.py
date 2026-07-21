from pathlib import Path

from cli import parser


def test_cli_exposes_archive_limit_configuration() -> None:
    arguments = parser().parse_args(
        ["book.epub", "--max-archive-entries", "2", "--max-output-bytes", "1024"]
    )

    assert arguments.epub_path == Path("book.epub")
    assert arguments.max_archive_entries == 2
    assert arguments.max_output_bytes == 1024
