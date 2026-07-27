# Library API Reference

The `epub-to-html` package exposes a clean Python API for integrations. All public types
are defined in `src/model.py`; the convenience entry point is in `src/api.py`.

---

## Quick Start

```python
from api import convert
from model import ConversionOptions

result = convert(
    "book.epub",
    "book.html",
    ConversionOptions(
        input_path="ignored.epub",
        output_path="ignored.html",
        safe_html=True,
        wrap_html=True,
    ),
)
print(f"Output: {result.output_path}")
print(f"Chapters: {result.documents_processed}")
```

The explicit path arguments always win. The supplied `ConversionOptions` contributes only
conversion policy — its `input_path` and `output_path` are replaced.

---

## Core Functions

### `api.convert(input_path, output_path, options=None)`

```python
def convert(
    input_path: Path | str,
    output_path: Path | str,
    options: ConversionOptions | None = None,
) -> ConversionResult
```

Convert an EPUB with path arguments and optional immutable policy overrides.

- **`input_path`** — Path to an EPUB file.
- **`output_path`** — Desired output HTML path.
- **`options`** — Conversion policy (see below). If omitted, all defaults apply.

Returns a `ConversionResult`.

---

### `converter.convert(options, observer=None, reader=None)`

```python
def convert(
    options: ConversionOptions,
    observer: ConversionObserver | None = None,
    reader: EpubReader | None = None,
) -> ConversionResult
```

The full conversion entry point. Used by the CLI and `api.convert()`.

- **`options`** — Full conversion policy (required).
- **`observer`** — Optional progress observer.
- **`reader`** — Optional EPUB reader (defaults to `EbookLibReader`).

---

### `batch.convert_batch(inputs, template, output_root, ...)`

```python
def convert_batch(
    inputs: Path | str | Iterable[Path | str],
    template: ConversionOptions,
    output_root: Path | str,
    workers: int = 1,
    worker_backend: str = "thread",
) -> BatchResult
```

Convert multiple EPUBs in parallel.

- **`inputs`** — One or more EPUB files or directories.
- **`template`** — Base `ConversionOptions` (applied to each input).
- **`output_root`** — Output directory.
- **`workers`** — Maximum concurrent workers.
- **`worker_backend`** — `"thread"` or `"process"`.

Returns a `BatchResult`.

---

### `inspection.inspect_epub(path, options)`

```python
def inspect_epub(path: Path, options: ConversionOptions) -> InspectionResult
```

Read-only EPUB inspection without creating output files. Returns metadata, spine
information, media inventory, layout signals, and unsupported features.

---

### Report Writers

```python
from report import write_html_report, write_json_report

write_html_report(path, result)  # Human-readable HTML report
write_json_report(path, result, options)  # Machine-readable JSON report
```

---

## Configuration

### `ConversionOptions`

Frozen dataclass with 25 fields.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `input_path` | `Path` | — | Input EPUB file |
| `output_path` | `Path` | — | Output HTML file |
| `image_strategy` | `Literal["embed", "extract"]` | `"embed"` | Embed images as data URLs or extract beside the HTML |
| `wrap_html` | `bool` | `False` | Add complete HTML document shell and default styling |
| `css` | `str \| None` | `None` | Inline trusted CSS content |
| `remove_toc` | `bool` | `False` | Remove detected table-of-contents elements |
| `remove_cover` | `bool` | `False` | Remove detected cover elements |
| `images_dir_name` | `str` | `"{stem}_files"` | Extracted image directory basename; `{stem}` expands to output filename stem |
| `chunked` | `bool` | `False` | Write prepared documents incrementally to staging |
| `safe_html` | `bool` | `False` | Remove active markup, unsafe URLs, EPUB CSS, SVG, invalid raster images |
| `force` | `bool` | `False` | Replace existing output |
| `archive_limits` | `ArchiveLimits` | `ArchiveLimits()` | Resource limits |
| `deadline_seconds` | `float \| None` | `None` | Cancel conversion after cooperative deadline |
| `cancellation_requested` | `Callable[[], bool] \| None` | `None` | Pollable cancellation check |
| `fail_on_warning` | `bool` | `False` | Abort if conversion warnings occur |
| `validate_output` | `bool` | `True` | Skip staged integrity checks when `False` |
| `stable_mime_types` | `bool` | `False` | Use filename-extension MIME types instead of host-dependent guessing |
| `newline` | `Literal["lf", "crlf"]` | `"lf"` | Output line endings |
| `navigation` | `bool` | `False` | Add auto-generated table of contents and back-to-top links |
| `navigation_depth` | `int` | `1` | Heading levels included in navigation (`1`–`6`) |
| `reader_theme` | `Literal["auto", "light", "dark"]` | `"auto"` | Wrapped reader color theme |
| `reader_max_width` | `str` | `"72ch"` | Wrapped reading width CSS value |
| `reader_font_family` | `str` | `"Georgia, serif"` | Wrapped reading font CSS value |
| `spine_range` | `tuple[int \| None, int \| None] \| None` | `None` | One-based inclusive chapter range |
| `exclude_content` | `frozenset[str]` | `frozenset()` | Categories to exclude: `cover`, `navigation`, `front-matter`, `endnotes`, `appendices` |
| `preserve_internal_css` | `bool` | `False` | Inline EPUB stylesheets; ignored by safe mode |
| `svg_policy` | `Literal["omit", "extract", "preserve"]` | `"omit"` | SVG handling |
| `mathml_policy` | `Literal["omit", "preserve"]` | `"omit"` | MathML handling |
| `media_policy` | `Literal["omit", "extract", "preserve"]` | `"omit"` | Audio/video resource handling |
| `font_policy` | `Literal["omit", "extract", "preserve"]` | `"omit"` | Embedded-font resource handling |

#### `ConversionOptions.from_args(cls, args, output_path, css=None)`

Build a `ConversionOptions` from an argparse namespace. Used internally by the CLI.

#### `ConversionOptions.validate()`

Raise `ValueError` if any field is invalid (called automatically by the converter).

---

### `ArchiveLimits`

Frozen dataclass with 8 resource limits.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `max_entries` | `int` | `10_000` | Maximum ZIP member count |
| `max_compressed_bytes` | `int` | `256 * 1024 * 1024` | Maximum compressed archive size |
| `max_expanded_bytes` | `int` | `1024 * 1024 * 1024` | Maximum expanded archive size |
| `max_entry_bytes` | `int` | `100 * 1024 * 1024` | Maximum expanded size of one archive member |
| `max_compression_ratio` | `float` | `1_000.0` | Maximum ZIP compression ratio |
| `max_documents` | `int` | `5_000` | Maximum EPUB document items |
| `max_images` | `int` | `10_000` | Maximum EPUB image items |
| `max_output_bytes` | `int` | `1024 * 1024 * 1024` | Maximum generated output size |

---

### `DocumentTransformConfig`

Frozen dataclass with 6 fields used by the document transformation pipeline.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `remove_toc` | `bool` | `False` | Remove table-of-contents elements |
| `remove_cover` | `bool` | `False` | Remove cover elements |
| `safe_html` | `bool` | `False` | Safe-mode active content removal |
| `excluded` | `frozenset[str]` | `frozenset()` | Content categories to exclude |
| `svg_policy` | `Literal["omit", "extract", "preserve"]` | `"omit"` | SVG handling |
| `mathml_policy` | `Literal["omit", "preserve"]` | `"omit"` | MathML handling |

---

## Result Types

### `ConversionResult`

Frozen dataclass representing a completed conversion.

| Field | Type | Description |
| --- | --- | --- |
| `output_path` | `Path` | Final output HTML file |
| `images_path` | `Path \| None` | Image output directory (extract mode) or `None` |
| `documents_processed` | `int` | Number of documents successfully processed |
| `images_processed` | `int` | Number of images processed |
| `skipped_images` | `int` | Number of images skipped |
| `skipped_documents` | `int` | Number of documents skipped |
| `output_bytes` | `int` | Size of the generated HTML output in bytes |
| `warnings` | `tuple[ConversionWarning, ...]` | Non-fatal conversion diagnostics |
| `duration_seconds` | `float` | Wall-clock conversion duration |
| `cancelled` | `bool` | Whether conversion was cancelled |
| `timed_out` | `bool` | Whether the deadline was exceeded |
| `peak_memory_bytes` | `int \| None` | Peak memory usage (if available) |
| `chapters` | `tuple[str, ...]` | Chapter labels (file paths or titles) |

### `ConversionWarning`

| Field | Type | Description |
| --- | --- | --- |
| `code` | `str` | Warning code (see [WARNINGS.md](WARNINGS.md)) |
| `message` | `str` | Human-readable description |
| `location` | `str \| None` | Source location (file path or item name) |

### `BatchResult`

| Field | Type | Description |
| --- | --- | --- |
| `results` | `tuple[BatchItemResult, ...]` | Per-item outcomes |
| `succeeded` | `int` | (computed) Number of successful conversions |
| `failed` | `int` | (computed) Number of failed conversions |

### `BatchItemResult`

| Field | Type | Description |
| --- | --- | --- |
| `input_path` | `Path` | Input EPUB file |
| `output_path` | `Path \| None` | Output HTML file (if successful) |
| `success` | `bool` | Whether conversion succeeded |
| `error` | `str \| None` | Error message (if failed) |

---

## Protocols

### `ConversionObserver`

```python
class ConversionObserver(Protocol):
    def phase(self, description: str, total: int | None = None, unit: str = "") -> None: ...
    def advance(self) -> None: ...
```

### `EpubReader`

```python
class EpubReader(Protocol):
    def read(self, path: Path, timeout: float | None = None) -> Any: ...
```

### `ImageOutput`

```python
class ImageOutput(Protocol):
    def register(self, item: Any) -> ImageReference: ...
```

---

## Errors

| Exception | Base | Description |
| --- | --- | --- |
| `ConversionError` | `Exception` | Base class for expected conversion failures |
| `InvalidEpubError` | `ConversionError` | Input cannot be accepted as an EPUB |
| `ArchiveLimitError` | `ConversionError` | Archive violates a configured resource policy |
| `OutputError` | `ConversionError` | Output cannot be written or committed safely |
| `ConversionCancelledError` | `ConversionError` | Conversion was cancelled or deadline exceeded |
| `OutputValidationError` | `ConversionError` | Staged HTML fails requested integrity checks |

---

## CLI Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Conversion completed successfully |
| `1` | Invalid input or expected conversion failure |
| `2` | Invalid command-line usage |
| `3` | Unexpected internal failure |
| `4` | Policy or validation rejection (archive limits, validation) |
| `5` | Output or report write failure |
| `130` | Conversion cancelled or deadline exceeded |
