"""Documented Python library API for EPUB-to-HTML integrations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from converter import convert as _convert
from model import ConversionOptions, ConversionResult


def convert(
    input_path: Path | str,
    output_path: Path | str,
    options: ConversionOptions | None = None,
) -> ConversionResult:
    """Convert an EPUB with path arguments and optional immutable policy overrides.

    When `options` is supplied, its policy fields are retained while its input and
    output paths are replaced with these explicit arguments.
    """
    input_value, output_value = Path(input_path), Path(output_path)
    request = (
        replace(options, input_path=input_value, output_path=output_value)
        if options
        else ConversionOptions(input_value, output_value)
    )
    return _convert(request)
