from pathlib import Path

from cli import parser


def test_cli_exposes_archive_limit_configuration() -> None:
    arguments = parser().parse_args(
        ["book.epub", "--max-archive-entries", "2", "--max-output-bytes", "1024"]
    )

    assert arguments.epub_path == Path("book.epub")
    assert arguments.max_archive_entries == 2
    assert arguments.max_output_bytes == 1024


def test_cli_exposes_operational_reliability_controls() -> None:
    arguments = parser().parse_args(
        [
            "book.epub",
            "--deadline-seconds",
            "5",
            "--fail-on-warning",
            "--stable-mime-types",
            "--newline",
            "crlf",
            "--report-json",
            "report.json",
        ]
    )

    assert arguments.deadline_seconds == 5
    assert arguments.fail_on_warning
    assert arguments.stable_mime_types
    assert arguments.newline == "crlf"
    assert arguments.report_json == Path("report.json")
