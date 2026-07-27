"""Rich progress observer for EPUB conversion."""

from __future__ import annotations

from rich.console import Console
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

from model import ConversionObserver

console = Console(stderr=True)


class RichProgressObserver(ConversionObserver):
    """Render converter phase events as concise status lines and progress bars."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def phase(self, description: str, total: int | None = None, unit: str = "") -> None:
        self._close_progress()
        if not self.enabled:
            return
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None) if total else TextColumn(""),
            TaskProgressColumn() if total else TextColumn(""),
            MofNCompleteColumn() if total else TextColumn(""),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(description, total=total, unit=unit)

    def advance(self) -> None:
        if self._progress and self._task_id is not None:
            self._progress.advance(self._task_id)

    def close(self) -> None:
        """Close the progress display cleanly."""
        self._close_progress()

    def _close_progress(self) -> None:
        if self._progress:
            self._progress.stop()
            self._progress = None
            self._task_id = None
