# Architecture

## Overview

`epub-to-html` converts EPUB publications into single HTML documents. The library is organized
around a clean pipeline: **validate → parse → transform → stage → commit**. Each phase is
handled by a dedicated module with a focused responsibility.

---

## Module Dependency Graph

```text
src/
├── api.py              → converter, model
├── batch.py            → converter, model
├── cli.py              → batch, completions, converter, inspection, model, progress, report
├── completions.py      → (standalone — argparse only)
├── converter.py        → html_transform, images, model, output, reader
├── html_transform.py   → images, model
├── images.py           → model
├── inspection.py       → converter, model, reader
├── model.py            → (zero internal imports)
├── output.py           → model
├── progress.py         → model
├── reader.py           → model
└── report.py           → model
```

`model.py` is the root of the dependency DAG — it has no internal imports. `converter.py` is the
central orchestrator. `cli.py` is the top-level entry point.

---

## Data Flow

```text
EPUB file
    │
    ▼
preflight_archive()       — ZIP validation, resource limits, path-traversal check
    │
    ▼
EbookLibReader.read()     — Parse EPUB structure via ebooklib (with optional timeout)
    │
    ▼
convert()                 — Main orchestrator
    ├── Categorize items: documents, images, resources, stylesheets
    ├── Enforce ArchiveLimits (documents, images, output bytes)
    ├── Open StagedOutput (temp staging directory)
    ├── _process_images() — ImageIndex registration (embed or extract)
    ├── _process_stylesheets() — CSS URL rewriting
    ├── build_targets() — Collision-safe anchor + ID map
    ├── _prepare_sections() — Per-document transform pipeline
    │       ├── decode_document() — UTF-8 → chardet → latin-1 fallback
    │       ├── Namespace IDs (collision-safe)
    │       ├── Rewrite cross-document links
    │       ├── rewrite_images() — ImageIndex resolution
    │       ├── remove_marked_content() — TOC, cover, excluded categories
    │       ├── SVG/MathML/audio/video policy filtering
    │       └── sanitize() — Safe-mode active content removal
    ├── _write_output() — 4 modes (wrap+chunked, wrap, chunked, plain)
    ├── Validation — output size, streaming HTML integrity check, fail-on-warning
    └── staged.commit() — AtomicPublisher: move with backup/rollback
```

---

## Key Design Patterns

### Protocol-based Dependency Injection

The core converter depends on protocols, not concrete implementations:

| Protocol | Module | Implementations |
| --- | --- | --- |
| `ConversionObserver` | `model.py` | `RichProgressObserver` (`progress.py`) |
| `EpubReader` | `model.py` | `EbookLibReader` (`reader.py`) |
| `ImageOutput` | `images.py` | `EmbeddedImageOutput`, `ExtractedImageOutput` |

### Immutable Configuration

`ConversionOptions` is a frozen dataclass — all fields are set at construction time and
cannot be mutated. The `from_args()` classmethod builds a policy from the argparse namespace
in one testable seam.

### Two-Phase Commit with Rollback

`StagedOutput` writes to a temporary staging directory. On success, `AtomicPublisher` moves
files into their final locations with a backup of any pre-existing files. If any move fails,
all moves are rolled back. The staging directory is cleaned up on context manager exit.

### Warning Collector

`WarningCollector` accumulates `ConversionWarning` instances with timing information.
Warnings are non-fatal diagnostics that describe skipped content, ambiguous references,
and encoding fallbacks.

---

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `model.py` | All domain types, errors, protocols, and configuration validation — the zero-dependency foundation. |
| `reader.py` | Thin concrete adapter wrapping `ebooklib.read_epub()` with optional timeout. |
| `converter.py` | Central conversion orchestrator: preflight, item categorization, pipeline sequencing, staging, validation, commit. |
| `html_transform.py` | All document-level transformations: decoding, ID namespacing, link rewriting, image resolution, content filtering, sanitization, HTML shell wrapping. |
| `images.py` | Image resource management: normalized path resolution, O(1) lookup index, two output strategies (embed/extract), safe-mode content validation. |
| `output.py` | Atomic file staging and commit with rollback — writes to a temp directory, then moves into place with backup/recovery. |
| `progress.py` | Rich terminal progress display — implements `ConversionObserver` with `rich.Progress` bars. |
| `cli.py` | Command-line entry point: argparse definition, plan/result printing, batch dispatch, error handling, report writing. |
| `completions.py` | Shell completion script generation (bash/zsh/fish/powershell) from the argparse parser. |
| `batch.py` | Batch conversion across multiple EPUBs: path expansion, parallel execution (thread/process), failure-isolated per-item results. |
| `api.py` | Clean public Python API — thin wrapper around `converter.convert()` accepting path arguments. |
| `inspection.py` | Read-only EPUB inspection: metadata, spine, media types, unsupported features, fixed-layout detection. |
| `report.py` | Post-conversion report generation: HTML human-readable and JSON machine-readable reports. |

---

## Image Processing Pipeline

1. **Categorization** — Items are split into images (`ITEM_IMAGE`, `ITEM_COVER`), resources
   (audio/video/font), and stylesheets (`text/css`).
2. **Strategy selection** — `EmbeddedImageOutput` (base64 data URLs) or `ExtractedImageOutput`
   (collision-safe file names in `{stem}_files/`).
3. **Registration** — Each image is registered into `ImageIndex`, which stores both full
   normalized paths and basename lookups.
4. **Resolution** — During `prepare_document()`, `rewrite_images()` resolves each `src`, `href`,
   `xlink:href`, `poster`, and `srcset` URL against the index. Resolution order: exact path →
   basename → ambiguous (warning) → missing (warning).
5. **Safe mode validation** — `supported_raster_image()` checks MIME type + magic bytes for
   PNG/JPEG/GIF/WebP only.
6. **CSS URL rewriting** — `rewrite_css_urls()` rewrites `url()` references in preserved
   internal stylesheets.

---

## Output Staging and Commit

```text
StagedOutput.__enter__()
  ├── Reject symlink/reparse-point paths
  ├── Fail if output exists (unless --force)
  ├── Create temp staging directory: .{stem}-staging-{random}/
  └── Set html_path, images_path within staging

Write to staged files via open_html()

Validation (optional):
  ├── Output size ≤ ArchiveLimits.max_output_bytes
  ├── _validate_staged_html() — streaming HTMLParser checks:
  │     - Duplicate IDs
  │     - Unresolved local fragment links
  │     - Unresolved local src references
  └── fail_on_warning check

staged.commit()
  ├── Backup directory: .{stem}-backup-{random}/
  ├── AtomicPublisher.publish(): move each file with rollback on failure
  ├── shutil.rmtree(backup)
  └── Mark committed=True

StagedOutput.__exit__()
  └── If not committed, shutil.rmtree(staging)
```

---

## Extension Points

To add a new output format, implement the `ImageOutput` protocol from `images.py` and register
it in the converter's `_process_images()` method.

To add a new progress backend, implement the `ConversionObserver` protocol from `model.py`.

To use a different EPUB parsing library, implement the `EpubReader` protocol from `model.py`
and inject it into `convert()`.
