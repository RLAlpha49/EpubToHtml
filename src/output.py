"""Transactional staged output for converted HTML and extracted assets."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import TextIO

from model import OutputError


class StagedOutput:
    """Write conversion results privately, then atomically publish them."""

    def __init__(self, output_path: Path, images_dir_name: str | None, force: bool) -> None:
        self.final_html = output_path
        self.final_images = output_path.parent / images_dir_name if images_dir_name else None
        self.force = force
        self.root: Path | None = None
        self.html_path: Path | None = None
        self.images_path: Path | None = None

    def __enter__(self) -> StagedOutput:
        if self.final_html.exists() and not self.force:
            raise OutputError(
                f"Output already exists: {self.final_html}. Use --force to replace it."
            )
        if self.final_images and self.final_images.exists() and not self.force:
            raise OutputError(
                f"Output already exists: {self.final_images}. Use --force to replace it."
            )
        self.final_html.parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(
            tempfile.mkdtemp(prefix=f".{self.final_html.stem}-staging-", dir=self.final_html.parent)
        )
        self.html_path = self.root / self.final_html.name
        self.images_path = self.root / self.final_images.name if self.final_images else None
        return self

    def open_html(self) -> TextIO:
        if self.html_path is None:
            raise OutputError("Output staging was not initialized")
        return self.html_path.open("w", encoding="utf-8", newline="\n")

    def size(self) -> int:
        return (
            sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
            if self.root
            else 0
        )

    def commit(self) -> None:
        if self.root is None or self.html_path is None:
            raise OutputError("Output staging was not initialized")
        backup = Path(
            tempfile.mkdtemp(prefix=f".{self.final_html.stem}-backup-", dir=self.final_html.parent)
        )
        moved: list[tuple[Path, Path]] = []
        committed: list[Path] = []
        try:
            for target in (self.final_html, self.final_images):
                if target and target.exists():
                    saved = backup / target.name
                    os.replace(target, saved)
                    moved.append((target, saved))
            os.replace(self.html_path, self.final_html)
            committed.append(self.final_html)
            if self.images_path and self.images_path.exists() and self.final_images:
                os.replace(self.images_path, self.final_images)
                committed.append(self.final_images)
        except OSError as error:
            for target in reversed(committed):
                shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(
                    missing_ok=True
                )
            for target, saved in reversed(moved):
                if saved.exists():
                    os.replace(saved, target)
            raise OutputError(f"Could not commit converted output: {error}") from error
        finally:
            shutil.rmtree(backup, ignore_errors=True)

    def __exit__(self, *_: object) -> None:
        if self.root:
            shutil.rmtree(self.root, ignore_errors=True)
