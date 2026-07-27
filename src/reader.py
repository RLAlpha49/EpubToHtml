"""Concrete EPUB reader backed by EbookLib."""

from __future__ import annotations

from pathlib import Path

from ebooklib import epub

from model import EpubReader


class EbookLibReader(EpubReader):
    """Read an EPUB file using the EbookLib library."""

    def read(self, path: Path) -> epub.EpubBook:
        """Open and return an EbookLib EPUB book."""
        return epub.read_epub(str(path))
