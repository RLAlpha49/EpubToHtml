"""Rich command-line adapter for the EPUB conversion library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

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

from converter import convert
from model import (
    ArchiveLimits,
    ConversionCancelledError,
    ConversionError,
    ConversionObserver,
    ConversionOptions,
    ConversionResult,
)

console = Console(stderr=True)


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
    result.add_argument("epub_path", type=Path, help="Path to the input EPUB file")
    result.add_argument(
        "-o", "--output", type=Path, default=Path("output.html"), help="Output HTML path"
    )
    result.add_argument(
        "-s",
        "--strategy",
        choices=("embed", "extract"),
        default="embed",
        help="Image output strategy",
    )
    result.add_argument(
        "-w", "--wrap", action="store_true", help="Wrap content in a complete HTML document"
    )
    result.add_argument("-c", "--css", type=Path, help="Inline a CSS file and enable --wrap")
    result.add_argument(
        "--remove-toc", action="store_true", help="Remove table-of-contents elements"
    )
    result.add_argument("--remove-cover", action="store_true", help="Remove cover elements")
    result.add_argument(
        "--images-dir-name", default="{stem}_files", help="Extracted-image directory name"
    )
    result.add_argument(
        "--chunked", action="store_true", help="Stream prepared documents to staged output"
    )
    result.add_argument(
        "--safe-mode", action="store_true", help="Sanitize active markup and unsafe URLs"
    )
    result.add_argument("--force", action="store_true", help="Replace existing output")
    result.add_argument(
        "--deadline-seconds", type=float, help="Cancel after this conversion deadline"
    )
    result.add_argument(
        "--fail-on-warning", action="store_true", help="Do not publish output if warnings occur"
    )
    result.add_argument(
        "--no-validate-output", action="store_true", help="Skip staged HTML integrity checks"
    )
    result.add_argument(
        "--stable-mime-types",
        action="store_true",
        help="Use extension-based MIME types instead of host-dependent guessing",
    )
    result.add_argument(
        "--newline", choices=("lf", "crlf"), default="lf", help="Output line ending"
    )
    result.add_argument(
        "--report-json", type=Path, help="Write a machine-readable local conversion report"
    )
    result.add_argument("--no-progress", action="store_true", help="Disable progress bars")
    result.add_argument(
        "--force-progress", action="store_true", help="Show progress bars without a TTY"
    )
    result.add_argument("--verbose", action="store_true", help="Show unexpected error tracebacks")
    result.add_argument("--max-archive-entries", type=int, default=ArchiveLimits.max_entries)
    result.add_argument(
        "--max-compressed-bytes", type=int, default=ArchiveLimits.max_compressed_bytes
    )
    result.add_argument("--max-expanded-bytes", type=int, default=ArchiveLimits.max_expanded_bytes)
    result.add_argument("--max-entry-bytes", type=int, default=ArchiveLimits.max_entry_bytes)
    result.add_argument(
        "--max-compression-ratio", type=float, default=ArchiveLimits.max_compression_ratio
    )
    result.add_argument("--max-documents", type=int, default=ArchiveLimits.max_documents)
    result.add_argument("--max-images", type=int, default=ArchiveLimits.max_images)
    result.add_argument("--max-output-bytes", type=int, default=ArchiveLimits.max_output_bytes)
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
        args.epub_path,
        args.output.resolve(),
        args.strategy,
        args.wrap or bool(css),
        css,
        args.remove_toc,
        args.remove_cover,
        args.images_dir_name,
        args.chunked,
        args.safe_mode,
        args.force,
        limits,
        args.deadline_seconds,
        None,
        args.fail_on_warning,
        not args.no_validate_output,
        args.stable_mime_types,
        args.newline,
    )


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


def _write_report(path: Path, result: ConversionResult) -> None:
    """Write a local JSON report for automation; no telemetry is sent."""
    path.write_text(
        json.dumps(
            {
                "status": "success",
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
        raise SystemExit(130 if isinstance(error, ConversionCancelledError) else 1) from error
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
        _write_report(args.report_json, result)


if __name__ == "__main__":
    main()
