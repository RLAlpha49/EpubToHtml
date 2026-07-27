"""Companion human-readable conversion report rendering."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from model import ConversionOptions, ConversionResult


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


def write_json_report(path: Path, result: ConversionResult, options: ConversionOptions) -> None:
    """Write a local JSON report for automation; no telemetry is sent."""
    path.write_text(
        json.dumps(
            {
                "status": "success",
                "tool_version": "1.0.0",
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
