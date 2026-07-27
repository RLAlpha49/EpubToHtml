import json
from pathlib import Path

from cli import parser, tool_version
from completions import COMPLETIONS
from model import ConversionOptions, ConversionResult
from report import write_json_report as write_report


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


def test_cli_accepts_product_feature_controls() -> None:
    arguments = parser().parse_args(
        [
            "book.epub",
            "--output",
            "out",
            "--workers",
            "2",
            "--spine-range",
            "2:4",
            "--exclude-content",
            "appendices",
            "--preserve-internal-css",
            "--svg-policy",
            "preserve",
            "--media-policy",
            "extract",
            "--report-html",
            "report.html",
        ]
    )

    assert arguments.output == Path("out")
    assert arguments.workers == 2
    assert arguments.spine_range == "2:4"
    assert arguments.exclude_content == ["appendices"]
    assert arguments.preserve_internal_css
    assert arguments.svg_policy == "preserve"
    assert arguments.media_policy == "extract"


def test_cli_uses_one_output_option_for_both_input_shapes(tmp_path: Path) -> None:
    from cli import resolve_output_path

    book = tmp_path / "book.epub"
    books = tmp_path / "books"
    books.mkdir()

    single = parser().parse_args([str(book)])
    directory = parser().parse_args([str(books)])

    assert resolve_output_path(single).name == "output.html"
    assert resolve_output_path(directory).name == "output"


def test_phase_three_options_map_from_parser_namespace(tmp_path: Path) -> None:
    arguments = parser().parse_args(
        [
            "book.epub",
            "--navigation",
            "--navigation-depth",
            "3",
            "--reader-theme",
            "dark",
            "--spine-range",
            "2:4",
        ]
    )

    options = ConversionOptions.from_args(arguments, tmp_path / "book.html")

    assert options.navigation_depth == 3
    assert options.reader_theme == "dark"
    assert options.spine_range == (2, 4)
    assert options.wrap_html
