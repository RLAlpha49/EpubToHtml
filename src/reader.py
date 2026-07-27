"""Concrete EPUB reader backed by EbookLib."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

from ebooklib import epub

from model import EpubReader


class EbookLibReader(EpubReader):
    """Read an EPUB file using the EbookLib library."""

    def read(self, path: Path, timeout: float | None = None) -> epub.EpubBook:
        """Open and return an EbookLib EPUB book.

        When *timeout* is provided, the read is performed in a separate thread
        and cancelled if it does not complete within the given number of
        seconds.  This prevents indefinite hangs on malformed EPUBs.
        """
        if timeout is None:
            return epub.read_epub(str(path))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(epub.read_epub, str(path))
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise TimeoutError(
                    f"EPUB read timed out after {timeout} second(s): {path}"
                ) from None
