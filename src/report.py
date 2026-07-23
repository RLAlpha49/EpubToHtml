"""Companion human-readable conversion report rendering."""

from __future__ import annotations

from html import escape
from pathlib import Path

from model import ConversionResult


def write_html_report(path: Path, result: ConversionResult) -> None:
    """Write an inert local report of output facts and conversion diagnostics."""
    warnings = (
        "".join(
            f"<li><strong>{escape(warning.code)}</strong>: {escape(warning.message)}"
            f"{f' ({escape(warning.location)})' if warning.location else ''}</li>"
            for warning in result.warnings
        )
        or "<li>None</li>"
    )
    chapters = (
        "".join(f"<li>{escape(chapter)}</li>" for chapter in result.chapters) or "<li>None</li>"
    )
    path.write_text(
        '<!DOCTYPE html><html lang="en"><meta charset="utf-8"><title>EPUB conversion report</title>'
        "<style>body{font:16px system-ui;max-width:72ch;margin:auto;padding:2rem}code{overflow-wrap:anywhere}</style>"
        "<h1>EPUB conversion report</h1>"
        f"<p><strong>Output:</strong> <code>{escape(str(result.output_path))}</code></p>"
        f"<p>{result.documents_processed} chapters; {result.images_processed} images; {result.output_bytes:,} bytes.</p>"
        f"<h2>Chapters</h2><ol>{chapters}</ol><h2>Warnings and policy findings</h2><ul>{warnings}</ul></html>",
        encoding="utf-8",
    )
