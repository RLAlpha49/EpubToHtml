"""Batch input and failure-isolated conversion orchestration."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from converter import convert as _convert_request
from model import BatchItemResult, BatchResult, ConversionError, ConversionOptions

convert_request: Any = _convert_request

WorkerBackend = Literal["thread", "process"]


def _convert_one(path: Path, output_root: Path, template: ConversionOptions) -> BatchItemResult:
    """Convert a single EPUB, returning a result for batch collection.

    This is a module-level function so it is picklable for
    ``ProcessPoolExecutor``.
    """
    try:
        request = replace(template, input_path=path, output_path=output_for(path, output_root))
        return BatchItemResult(path, result=convert_request(request))
    except (ConversionError, OSError, ValueError) as error:
        return BatchItemResult(path, error=str(error))


def expand_inputs(inputs: tuple[Path, ...]) -> tuple[Path, ...]:
    """Expand EPUB files, directories, and glob patterns into stable unique paths."""
    found: dict[Path, None] = {}
    for value in inputs:
        matches = (
            sorted(value.parent.glob(value.name))
            if any(char in value.name for char in "*?[")
            else [value]
        )
        for match in matches:
            candidates = sorted(match.rglob("*.epub")) if match.is_dir() else [match]
            for candidate in candidates:
                if candidate.is_file() and candidate.suffix.lower() == ".epub":
                    found[candidate.resolve()] = None
    return tuple(found)


def output_for(input_path: Path, output_root: Path) -> Path:
    """Create a predictable per-book output name beneath a batch output root."""
    return output_root / f"{input_path.stem}.html"


def convert_batch(
    inputs: tuple[Path, ...],
    template: ConversionOptions,
    output_root: Path,
    workers: int = 1,
    worker_backend: WorkerBackend = "thread",
) -> BatchResult:
    """Convert each expanded book independently and retain every outcome.

    Parameters
    ----------
    inputs
        Paths to expand (files, directories, or glob patterns).
    template
        Base conversion options; ``input_path`` and ``output_path`` are
        replaced per book.
    output_root
        Directory where per-book HTML files are written.
    workers
        Number of parallel workers.  ``1`` always runs sequentially.
    worker_backend
        ``"thread"`` (default, GIL-bound) or ``"process"`` (true parallelism
        for CPU-bound BeautifulSoup/base64 work).  Ignored when ``workers == 1``.
    """
    if workers < 1:
        raise ValueError("workers must be at least one")
    if worker_backend not in ("thread", "process"):
        raise ValueError("worker_backend must be 'thread' or 'process'")
    paths = expand_inputs(inputs)

    if workers == 1:
        return BatchResult(tuple(_convert_one(path, output_root, template) for path in paths))

    executor_cls = ProcessPoolExecutor if worker_backend == "process" else ThreadPoolExecutor
    with executor_cls(max_workers=workers) as executor:
        futures = [executor.submit(_convert_one, path, output_root, template) for path in paths]
        return BatchResult(tuple(future.result() for future in futures))
