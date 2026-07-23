import json
from pathlib import Path

from cli import COMPLETIONS, parser, tool_version, write_report
from model import ConversionOptions, ConversionResult


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


def test_cli_groups_discoverable_options_and_accepts_presentation_controls() -> None:
    arguments = parser().parse_args(
        [
            "book.epub",
            "--navigation",
            "--reader-max-width",
            "65ch",
            "--reader-font-family",
            "system-ui",
        ]
    )

    assert arguments.navigation
    assert arguments.reader_max_width == "65ch"
    assert arguments.reader_font_family == "system-ui"
    assert "Input and output" in parser().format_help()
    assert "Safety and reliability" in parser().format_help()


def test_wrapped_output_options_enable_wrapping_without_wrap_flag() -> None:
    arguments = parser().parse_args(["book.epub", "--navigation"])
    assert arguments.navigation
    assert arguments.wrap is False
    assert arguments.reader_max_width is None
    assert arguments.reader_font_family is None


def test_completion_scripts_cover_all_options_and_choice_values() -> None:
    for shell in ("bash", "zsh", "fish", "powershell"):
        script = COMPLETIONS[shell]
        option_marker = "-l max-output-bytes" if shell == "fish" else "--max-output-bytes"
        font_marker = "-l reader-font-family" if shell == "fish" else "--reader-font-family"
        assert option_marker in script
        assert font_marker in script
        if shell == "fish":
            assert "-s o" in script and "-s s" in script
        else:
            assert "-o" in script and "-s" in script
        assert "embed" in script and "extract" in script
        assert "lf" in script and "crlf" in script
        assert "powershell" in script


def test_report_includes_tool_version_and_policy(tmp_path: Path) -> None:
    output = tmp_path / "book.html"
    options = ConversionOptions(tmp_path / "book.epub", output, navigation=True)
    result = ConversionResult(output, None, 1, 0, 0, 0, 0, (), 0.1, False, False)
    report = tmp_path / "report.json"

    write_report(report, result, options)

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["tool_version"] == tool_version()
    assert payload["input_path"] == str(options.input_path)
    assert payload["policy"]["navigation"] is True
