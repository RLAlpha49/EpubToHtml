"""Rich command-line adapter for the EPUB conversion library."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, NoReturn, cast

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from batch import convert_batch
from converter import convert
from inspection import inspect_epub
from model import (
    ArchiveLimitError,
    ArchiveLimits,
    ConversionCancelledError,
    ConversionError,
    ConversionObserver,
    ConversionOptions,
    ConversionResult,
    OutputError,
    OutputValidationError,
)
from report import write_html_report

console = Console(stderr=True)


def tool_version() -> str:
    """Report installed package metadata while allowing checkout execution."""
    try:
        return version("epub-to-html")
    except PackageNotFoundError:
        return "1.0.0"


ALL_OPTIONS = (
    "--help",
    "--version",
    "--print-completion",
    "--output",
    "--workers",
    "--inspect",
    "--strategy",
    "--wrap",
    "--css",
    "--remove-toc",
    "--remove-cover",
    "--images-dir-name",
    "--chunked",
    "--safe-mode",
    "--navigation",
    "--reader-max-width",
    "--reader-font-family",
    "--force",
    "--deadline-seconds",
    "--fail-on-warning",
    "--no-validate-output",
    "--stable-mime-types",
    "--newline",
    "--report-json",
    "--report-html",
    "--spine-range",
    "--exclude-content",
    "--preserve-internal-css",
    "--svg-policy",
    "--mathml-policy",
    "--media-policy",
    "--font-policy",
    "--no-progress",
    "--force-progress",
    "--verbose",
    "--max-archive-entries",
    "--max-compressed-bytes",
    "--max-expanded-bytes",
    "--max-entry-bytes",
    "--max-compression-ratio",
    "--max-documents",
    "--max-images",
    "--max-output-bytes",
)
SHORT_OPTIONS = ("-h", "-o", "-s", "-w", "-c")
_COMPLETION_WORDS = " ".join((*ALL_OPTIONS, *SHORT_OPTIONS))

COMPLETIONS = {
    "bash": f'''_epub_to_html_complete() {{
    local current="${{COMP_WORDS[COMP_CWORD]}}"
    local previous="${{COMP_WORDS[COMP_CWORD-1]}}"
    case "$previous" in
        --strategy) COMPREPLY=($(compgen -W "embed extract" -- "$current")); return ;;
        --newline) COMPREPLY=($(compgen -W "lf crlf" -- "$current")); return ;;
        --print-completion) COMPREPLY=($(compgen -W "bash zsh fish powershell" -- "$current")); return ;;
        --output|--css|--report-json|--images-dir-name|--reader-max-width|--reader-font-family|--deadline-seconds|--max-*) return ;;
    esac
    COMPREPLY=($(compgen -W "{_COMPLETION_WORDS}" -- "$current"))
}}
complete -F _epub_to_html_complete epub-to-html''',
    "zsh": """#compdef epub-to-html
_arguments \\
    '1:EPUB file:_files -g "*.epub"' \\
    '(-h --help)'{-h,--help}'[Show help and exit]' \\
    '(-s --strategy)'{-s,--strategy}'[Image strategy]:strategy:(embed extract)' \\
    '(-w --wrap)'{-w,--wrap}'[Wrap output]' \\
    '(-c --css)'{-c,--css}'[Trusted stylesheet]:file:_files' \\
    '--help[Show help and exit]' '--version[Show version and exit]' \\
    '--print-completion[Print completion script]:shell:(bash zsh fish powershell)' \\
    '(-o --output)-o[Output HTML path]:path:_files' \\
    '--output[Output HTML path]:path:_files' \\
    '--strategy[Image strategy]:strategy:(embed extract)' '--wrap[Wrap output]' \\
    '--css[Trusted stylesheet]:file:_files' '--remove-toc[Remove TOC]' '--remove-cover[Remove cover]' \\
    '--images-dir-name[Extracted image directory]:name:' '--chunked[Stream staged output]' \\
    '--safe-mode[Sanitize active content]' '--navigation[Add generated navigation]' \\
    '--reader-max-width[Wrapped reading width]:width:' '--reader-font-family[Wrapped font]:font:' \\
    '--force[Replace existing output]' '--deadline-seconds[Conversion deadline]:seconds:' \\
    '--fail-on-warning[Reject warnings]' '--no-validate-output[Skip output validation]' \\
    '--stable-mime-types[Use stable MIME types]' '--newline[Output line ending]:line ending:(lf crlf)' \\
    '--report-json[Write JSON report]:file:_files' '--no-progress[Disable progress]' \\
    '--force-progress[Show progress without TTY]' '--verbose[Show traceback]' \\
    '--max-archive-entries[Maximum ZIP members]:number:' '--max-compressed-bytes[Maximum compressed bytes]:number:' \\
    '--max-expanded-bytes[Maximum expanded bytes]:number:' '--max-entry-bytes[Maximum member bytes]:number:' \\
    '--max-compression-ratio[Maximum compression ratio]:number:' '--max-documents[Maximum documents]:number:' \\
    '--max-images[Maximum images]:number:' '--max-output-bytes[Maximum output bytes]:number:' """,
    "fish": "\n".join(
        [
            "complete -c epub-to-html -f -a '*.epub'",
            *[f"complete -c epub-to-html -l {option[2:]}" for option in ALL_OPTIONS],
            "complete -c epub-to-html -s h -d 'Show help and exit'",
            "complete -c epub-to-html -s o -r -d 'Output HTML path'",
            "complete -c epub-to-html -s s -xa 'embed extract' -d 'Image strategy'",
            "complete -c epub-to-html -s w -d 'Wrap output'",
            "complete -c epub-to-html -s c -r -d 'Trusted stylesheet'",
            "complete -c epub-to-html -l strategy -xa 'embed extract'",
            "complete -c epub-to-html -l newline -xa 'lf crlf'",
            "complete -c epub-to-html -l print-completion -xa 'bash zsh fish powershell'",
        ]
    ),
    "powershell": f"""Register-ArgumentCompleter -CommandName epub-to-html -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $options = @({", ".join(repr(option) for option in (*ALL_OPTIONS, *SHORT_OPTIONS))})
    $values = @{{ '--strategy' = @('embed', 'extract'); '--newline' = @('lf', 'crlf'); '--print-completion' = @('bash', 'zsh', 'fish', 'powershell') }}
    $previous = $commandAst.CommandElements[$commandAst.CommandElements.Count - 2].Value
    if ($values.ContainsKey($previous)) {{ $options = $values[$previous] }}
    $options | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_) }}
}}""",
}


class PrintCompletionAction(argparse.Action):
    """Print a small static completion script before positional validation runs."""

    def __call__(
        self,
        parser_: argparse.ArgumentParser,
        _namespace: argparse.Namespace,
        value: str | Sequence[Any] | None,
        _option_string: str | None = None,
    ) -> None:
        del _namespace, _option_string
        if isinstance(value, str):
            parser_.exit(message=COMPLETIONS[value] + "\n")
        parser_.error("--print-completion requires a shell name")


class RichArgumentParser(argparse.ArgumentParser):
    """Render help and parser errors using the interactive CLI style."""

    def error(self, message: str) -> NoReturn:
        console.print(Panel(message, title="[bold red]Invalid command[/]", border_style="red"))
        console.print(self.format_usage().strip(), style="dim")
        raise SystemExit(2)


class RichProgressObserver(ConversionObserver):
    """Render converter phase events as concise status lines and progress bars."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def phase(self, description: str, total: int | None = None, unit: str = "") -> None:
        self._close_progress()
        if total is None:
            console.print(f"[bold cyan]•[/] {description}...")
            return
        if not self.enabled:
            console.print(f"[bold cyan]•[/] {description}: {total} {unit}...")
            return
        self._progress = Progress(
            SpinnerColumn(style="bright_cyan"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(f"{description} ({unit})", total=total)

    def advance(self) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.advance(self._task_id)

    def close(self) -> None:
        self._close_progress()

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.stop()
        self._progress = None
        self._task_id = None


def parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    result = RichArgumentParser(description="Convert an EPUB publication into one HTML document.")
    result.add_argument("--version", action="version", version=f"%(prog)s {tool_version()}")
    result.add_argument(
        "--print-completion", choices=tuple(COMPLETIONS), action=PrintCompletionAction
    )
    input_output = result.add_argument_group("Input and output")
    content = result.add_argument_group("Content and presentation")
    safety = result.add_argument_group("Safety and reliability")
    diagnostics = result.add_argument_group("Diagnostics and automation")
    input_output.add_argument(
        "epub_path", type=Path, help="Input EPUB file, or directory containing EPUB files"
    )
    input_output.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file for one EPUB, or directory for an EPUB directory",
    )
    input_output.add_argument("--workers", type=int, default=1, help="Batch workers; default: 1")
    input_output.add_argument(
        "--inspect", action="store_true", help="Inspect input without creating conversion output"
    )
    input_output.add_argument(
        "-s",
        "--strategy",
        choices=("embed", "extract"),
        default="embed",
        help="Image output strategy; default: embed",
    )
    content.add_argument(
        "-w", "--wrap", action="store_true", help="Wrap content in a complete HTML document"
    )
    content.add_argument(
        "-c", "--css", type=Path, help="Inline a trusted local stylesheet and enable --wrap"
    )
    content.add_argument(
        "--remove-toc", action="store_true", help="Remove table-of-contents elements"
    )
    content.add_argument("--remove-cover", action="store_true", help="Remove cover elements")
    content.add_argument(
        "--spine-range", help="One-based inclusive chapter range, for example 2:8 or 5:"
    )
    content.add_argument(
        "--exclude-content",
        action="append",
        choices=("cover", "navigation", "front-matter", "endnotes", "appendices"),
        default=[],
        help="Exclude a semantic content category; repeatable",
    )
    content.add_argument(
        "--images-dir-name", default="{stem}_files", help="Extracted-image directory name"
    )
    content.add_argument(
        "--chunked", action="store_true", help="Stream prepared documents to staged output"
    )
    content.add_argument(
        "--safe-mode", action="store_true", help="Sanitize active markup and unsafe URLs"
    )
    content.add_argument(
        "--preserve-internal-css",
        action="store_true",
        help="Inline EPUB stylesheets and rewrite local URLs",
    )
    content.add_argument("--svg-policy", choices=("omit", "extract", "preserve"), default="omit")
    content.add_argument("--mathml-policy", choices=("omit", "preserve"), default="omit")
    content.add_argument("--media-policy", choices=("omit", "extract", "preserve"), default="omit")
    content.add_argument("--font-policy", choices=("omit", "extract", "preserve"), default="omit")
    content.add_argument(
        "--navigation",
        action="store_true",
        help="Add an opt-in table of contents and back-to-top links",
    )
    content.add_argument(
        "--reader-max-width",
        help="Set reading width and automatically enable wrapping; default: 72ch",
    )
    content.add_argument(
        "--reader-font-family",
        help="Set reading font and automatically enable wrapping; default: Georgia, serif",
    )
    safety.add_argument("--force", action="store_true", help="Replace existing output")
    safety.add_argument(
        "--deadline-seconds", type=float, help="Cancel after this conversion deadline"
    )
    safety.add_argument(
        "--fail-on-warning", action="store_true", help="Do not publish output if warnings occur"
    )
    safety.add_argument(
        "--no-validate-output", action="store_true", help="Skip staged HTML integrity checks"
    )
    safety.add_argument(
        "--stable-mime-types",
        action="store_true",
        help="Use extension-based MIME types instead of host-dependent guessing",
    )
    safety.add_argument(
        "--newline", choices=("lf", "crlf"), default="lf", help="Output line ending; default: lf"
    )
    diagnostics.add_argument(
        "--report-json", type=Path, help="Write a machine-readable local conversion report"
    )
    diagnostics.add_argument(
        "--report-html", type=Path, help="Write a companion HTML validation report"
    )
    diagnostics.add_argument("--no-progress", action="store_true", help="Disable progress bars")
    diagnostics.add_argument(
        "--force-progress", action="store_true", help="Show progress bars without a TTY"
    )
    diagnostics.add_argument(
        "--verbose", action="store_true", help="Show unexpected error tracebacks"
    )
    safety.add_argument(
        "--max-archive-entries",
        type=int,
        default=ArchiveLimits.max_entries,
        help="Maximum ZIP members; default: 10000",
    )
    safety.add_argument(
        "--max-compressed-bytes",
        type=int,
        default=ArchiveLimits.max_compressed_bytes,
        help="Maximum compressed archive bytes; default: 268435456",
    )
    safety.add_argument(
        "--max-expanded-bytes",
        type=int,
        default=ArchiveLimits.max_expanded_bytes,
        help="Maximum expanded archive bytes; default: 1073741824",
    )
    safety.add_argument(
        "--max-entry-bytes",
        type=int,
        default=ArchiveLimits.max_entry_bytes,
        help="Maximum expanded member bytes; default: 104857600",
    )
    safety.add_argument(
        "--max-compression-ratio",
        type=float,
        default=ArchiveLimits.max_compression_ratio,
        help="Maximum ZIP compression ratio; default: 1000",
    )
    safety.add_argument(
        "--max-documents",
        type=int,
        default=ArchiveLimits.max_documents,
        help="Maximum document items; default: 5000",
    )
    safety.add_argument(
        "--max-images",
        type=int,
        default=ArchiveLimits.max_images,
        help="Maximum image items; default: 10000",
    )
    safety.add_argument(
        "--max-output-bytes",
        type=int,
        default=ArchiveLimits.max_output_bytes,
        help="Maximum generated bytes; default: 1073741824",
    )
    return result


def _options(args: argparse.Namespace) -> ConversionOptions:
    css = args.css.read_text(encoding="utf-8") if args.css else None
    limits = ArchiveLimits(
        args.max_archive_entries,
        args.max_compressed_bytes,
        args.max_expanded_bytes,
        args.max_entry_bytes,
        args.max_compression_ratio,
        args.max_documents,
        args.max_images,
        args.max_output_bytes,
    )
    return ConversionOptions(
        input_path=args.epub_path,
        output_path=resolve_output_path(args),
        image_strategy=args.strategy,
        wrap_html=(
            args.wrap
            or bool(css)
            or args.navigation
            or args.reader_max_width is not None
            or args.reader_font_family is not None
        ),
        css=css,
        remove_toc=args.remove_toc,
        remove_cover=args.remove_cover,
        images_dir_name=args.images_dir_name,
        chunked=args.chunked,
        safe_html=args.safe_mode,
        force=args.force,
        archive_limits=limits,
        deadline_seconds=args.deadline_seconds,
        fail_on_warning=args.fail_on_warning,
        validate_output=not args.no_validate_output,
        stable_mime_types=args.stable_mime_types,
        newline=args.newline,
        navigation=args.navigation,
        reader_max_width=args.reader_max_width or "72ch",
        reader_font_family=args.reader_font_family or "Georgia, serif",
        spine_range=_parse_spine_range(args.spine_range),
        exclude_content=frozenset(args.exclude_content),
        preserve_internal_css=args.preserve_internal_css,
        svg_policy=args.svg_policy,
        mathml_policy=args.mathml_policy,
        media_policy=args.media_policy,
        font_policy=args.font_policy,
    )


def resolve_output_path(args: argparse.Namespace) -> Path:
    """Choose the default output shape from the input shape."""
    output = cast(Path | None, args.output)
    if output:
        return output.resolve()
    return (Path("output") if args.epub_path.is_dir() else Path("output.html")).resolve()


def _parse_spine_range(value: str | None) -> tuple[int | None, int | None] | None:
    if value is None:
        return None
    try:
        start_text, end_text = value.split(":", 1)
        start = int(start_text) if start_text else None
        end = int(end_text) if end_text else None
    except ValueError as error:
        raise ValueError("spine range must use START:END notation") from error
    return start, end


def _print_plan(options: ConversionOptions) -> None:
    plan = Table.grid(padding=(0, 1))
    plan.add_column(style="bold cyan", justify="right")
    plan.add_column()
    plan.add_row("Source", str(options.input_path))
    plan.add_row("Destination", str(options.output_path))
    plan.add_row("Images", options.image_strategy)
    plan.add_row("Content", "safe mode" if options.safe_html else "source fidelity")
    plan.add_row("Processing", "chunked" if options.chunked else "standard")
    console.print(
        Group(
            Panel.fit(Text("EPUB → HTML", style="bold bright_cyan"), border_style="bright_cyan"),
            Panel(plan, border_style="blue"),
        )
    )


def _print_result(result: ConversionResult) -> None:
    summary = Table.grid(padding=(0, 1))
    summary.add_column(style="bold cyan", justify="right")
    summary.add_column()
    summary.add_row("Documents", str(result.documents_processed))
    summary.add_row("Images processed", str(result.images_processed))
    summary.add_row("Skipped images", str(result.skipped_images))
    summary.add_row("Skipped documents", str(result.skipped_documents))
    summary.add_row("Duration", f"{result.duration_seconds:.2f}s")
    summary.add_row("Input size", f"{result.input_bytes:,} bytes")
    summary.add_row("Output size", f"{result.output_bytes:,} bytes")
    if result.images_path:
        summary.add_row("Images directory", str(result.images_path))
    summary.add_row("HTML output", str(result.output_path))
    console.print(Panel(summary, title="[bold green]Conversion complete[/]", border_style="green"))
    for warning in result.warnings[:10]:
        location = f" ({warning.location})" if warning.location else ""
        console.print(f"[yellow]Warning:[/] {warning.message}{location}")
    if len(result.warnings) > 10:
        console.print(f"[yellow]… and {len(result.warnings) - 10} more warning(s).[/]")


def write_report(path: Path, result: ConversionResult, options: ConversionOptions) -> None:
    """Write a local JSON report for automation; no telemetry is sent."""
    path.write_text(
        json.dumps(
            {
                "status": "success",
                "tool_version": tool_version(),
                "input_path": str(options.input_path),
                "output_path": str(result.output_path),
                "images_path": str(result.images_path) if result.images_path else None,
                "documents_processed": result.documents_processed,
                "images_processed": result.images_processed,
                "skipped_images": result.skipped_images,
                "skipped_documents": result.skipped_documents,
                "decode_fallbacks": result.decode_fallbacks,
                "duration_seconds": result.duration_seconds,
                "input_bytes": result.input_bytes,
                "output_bytes": result.output_bytes,
                "warnings": [warning.__dict__ for warning in result.warnings],
                "policy": {
                    "image_strategy": options.image_strategy,
                    "safe_mode": result.safe_html,
                    "chunked": result.chunked,
                    "navigation": options.navigation,
                    "validate_output": options.validate_output,
                    "newline": options.newline,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Run conversion with useful terminal feedback while keeping the core reusable."""
    args = parser().parse_args()
    try:
        options = _options(args)
        input_is_directory = args.epub_path.is_dir()
        if not args.epub_path.is_file() and not input_is_directory:
            raise ValueError(f"Input must be an existing EPUB file or directory: {args.epub_path}")
        if input_is_directory and options.output_path.exists() and not options.output_path.is_dir():
            raise ValueError("A directory input requires --output to be a directory")
        if not input_is_directory and options.output_path.exists() and options.output_path.is_dir():
            raise ValueError("A single-file input requires --output to be an HTML file")
        if args.inspect:
            if input_is_directory:
                raise ValueError("--inspect requires one EPUB file, not a directory")
            inspection_payload = inspect_epub(args.epub_path, options).as_dict()
            console.print_json(json.dumps(inspection_payload))
            return
        if input_is_directory:
            if args.workers < 1:
                raise ValueError("workers must be at least one")
            batch = convert_batch((args.epub_path,), options, options.output_path, args.workers)
            payload: dict[str, object] = {
                "succeeded": batch.succeeded,
                "failed": batch.failed,
                "items": [
                    {
                        "input_path": str(item.input_path),
                        "output_path": str(item.result.output_path) if item.result else None,
                        "error": item.error,
                    }
                    for item in batch.items
                ],
            }
            console.print_json(json.dumps(payload))
            if args.report_json:
                args.report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            if batch.failed:
                raise ConversionError(f"{batch.failed} batch item(s) failed")
            return
        _print_plan(options)
        enabled = not args.no_progress and (args.force_progress or sys.stderr.isatty())
        observer = RichProgressObserver(enabled)
        try:
            result = convert(options, observer)
        finally:
            observer.close()
    except KeyboardInterrupt:
        console.print(
            Panel("Conversion cancelled.", title="[bold yellow]Cancelled[/]", border_style="yellow")
        )
        raise SystemExit(130) from None
    except (ConversionError, OSError, ValueError) as error:
        console.print(Panel(str(error), title="[bold red]Conversion failed[/]", border_style="red"))
        if isinstance(error, ConversionCancelledError):
            exit_code = 130
        elif isinstance(error, (ArchiveLimitError, OutputValidationError)):
            exit_code = 4
        elif isinstance(error, (OutputError, OSError)):
            exit_code = 5
        else:
            exit_code = 1
        raise SystemExit(exit_code) from error
    except Exception:
        if args.verbose:
            console.print_exception()
        else:
            console.print(
                Panel(
                    "Unexpected conversion error. Rerun with --verbose for a traceback.",
                    title="[bold red]Conversion failed[/]",
                    border_style="red",
                )
            )
        raise SystemExit(3) from None
    _print_result(result)
    if args.report_json:
        try:
            write_report(args.report_json, result, options)
        except OSError as error:
            console.print(Panel(str(error), title="[bold red]Report failed[/]", border_style="red"))
            raise SystemExit(5) from error
    if args.report_html:
        try:
            write_html_report(args.report_html, result)
        except OSError as error:
            console.print(Panel(str(error), title="[bold red]Report failed[/]", border_style="red"))
            raise SystemExit(5) from error


if __name__ == "__main__":
    main()
