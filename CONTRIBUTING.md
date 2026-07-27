# Contributing

## Development setup

Use Python 3.12+. Install the complete local toolchain with:

```bash
python -m pip install -e ".[dev]"
```

## Canonical commands

Nox is the project command interface on every platform:

- `python -m nox -- format` checks formatting.
- `python -m nox -- lint` runs Ruff lint rules.
- `python -m nox -- typecheck` runs mypy using the committed EbookLib stubs.
- `python -m nox -- tests` runs pytest on supported Python versions.
- `python -m nox -- coverage` runs pytest with coverage reporting (XML + terminal).
- `python -m nox -- build` builds a wheel, installs it, and checks `epub-to-html --help`.
- `python -m nox -- security` runs `bandit` security scan on `src/`.
- `python -m nox -- lock` regenerates `requirements.txt` and `requirements.lock` from `pyproject.toml`.

Run `python -m nox` before opening a pull request.

## Testing strategy

The test suite is organized into focused modules under `tests/`:

| File | Scope |
| --- | --- |
| `test_archive.py` | EPUB archive preflight policy (entry limits, path traversal, compression ratios). |
| `test_html_transform.py` | Document decoding, ID rewriting, sanitization, image rewriting, wrapping. |
| `test_images.py` | Image index resolution, basename fallback, safe-mode signature checks. |
| `test_model_and_output.py` | Option validation, staged output commit/rollback, cancellation, HTML validation. |
| `test_product_features.py` | End-to-end product behavior: CSS rewriting, batch isolation, library API, HTML reports. |
| `test_integration.py` | Full `convert()` pipeline against real (synthetic) EPUB archives built with `zipfile`. |
| `test_cli.py` | Argument parsing, completion script coverage, JSON report output. |

### Writing tests

- Use the `epub_builder` fixture from `tests/conftest.py` to create minimal EPUB archives in a temporary directory.
- Prefer integration tests that exercise the full `convert()` pipeline over isolated unit tests when the behavior spans multiple modules.
- Add a regression test whenever a change alters observable conversion behavior.
- Run a single test file with `python -m pytest tests/test_html_transform.py`.

## Code style

The project uses [Ruff](https://docs.astral.sh/ruff/) for formatting and linting. All code must pass:

```bash
python -m ruff format --check .
python -m ruff check .
```

Key conventions:

- **Line length**: 100 characters (enforced by the formatter).
- **Import sorting**: `isort` rules via Ruff (`I`).
- **Type annotations**: All public functions and methods must have type annotations. Use `from __future__ import annotations` at the top of every module.
- **Docstrings**: Use triple-quoted strings for module, class, and public function docstrings.
- **Comments**: Write clear, plain-spoken comments. Avoid redundant or "AI-flavored" commentary.

## Type checking

```bash
python -m mypy
```

- Type stubs for `ebooklib` are committed under `typings/ebooklib/` and configured via `mypy_path` in `pyproject.toml`.
- The package includes a `py.typed` marker so downstream consumers of the library API also get type information.

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Common types:

| Type | Use |
| --- | --- |
| `feat` | A new feature. |
| `fix` | A bug fix. |
| `refactor` | A code change that neither fixes a bug nor adds a feature. |
| `perf` | A code change that improves performance. |
| `test` | Adding or correcting tests. |
| `docs` | Documentation-only changes. |
| `chore` | Maintenance tasks (dependencies, tooling, CI). |

Example:

```text
fix(html_transform): reject non-image data URLs in safe mode

The safe_url() function accepted data: URLs with any MIME type that
started with "image/". This allowed data:text/html,... payloads to
pass through. Now only image/png, image/jpeg, image/gif, and
image/webp are accepted.
```

## Pull request checklist

Before submitting a pull request:

- [ ] `python -m nox` passes (format, lint, typecheck, tests, build).
- [ ] New code is covered by tests; `python -m pytest` passes.
- [ ] Type checking passes: `python -m mypy`.
- [ ] Linting passes: `python -m ruff check .` and `python -m ruff format --check .`.
- [ ] Commit messages follow Conventional Commits.
- [ ] If the change affects user-visible behavior, update `README.md`.
- [ ] If the change adds or removes a CLI option, update the completion scripts and `ALL_OPTIONS`.
- [ ] If the change adds a new warning code, document it in the README.

## Architecture overview

The project follows a layered architecture with clear separation of concerns:

```test
src/
├── api.py            # Public library API (convert with path overrides)
├── batch.py          # Batch conversion with failure isolation
├── cli.py            # Rich CLI adapter (argument parsing, progress, reports)
├── completions.py    # Shell completion scripts (bash, zsh, fish, powershell)
├── converter.py      # Core conversion service (preflight, decode, transform, write)
├── html_transform.py # Document decoding and one-pass HTML transformations
├── images.py         # Image output strategies and EPUB image lookup indexes
├── inspection.py     # Read-only EPUB inspection for planning/diagnosis
├── model.py          # Immutable policy, result, diagnostics, and domain errors
├── output.py         # Transactional staged output (atomic commit/rollback)
├── progress.py       # Rich progress observer for CLI feedback
└── report.py         # Human-readable and machine-readable report writers
```

**Data flow:**

1. `cli.py` parses arguments into `ConversionOptions`.
2. `converter.convert()` validates the archive (`preflight_archive`), reads the EPUB (`epub.read_epub`), classifies items, processes images, decodes documents, builds ID targets, prepares sections, and writes output.
3. `html_transform.py` handles all per-document transformations: decoding, ID rewriting, link rewriting, image rewriting, content filtering, sanitization, and wrapping.
4. `images.py` manages image registration (embed as data URLs or extract to disk) and provides the `ImageIndex` for resolving EPUB-local image references.
5. `output.py` provides `StagedOutput` for atomic, rollback-safe output publishing.
6. `report.py` writes JSON and HTML reports for automation and human review.

**Extension points:**

- `ConversionObserver` protocol: implement to receive phase/advance events (e.g., for custom progress UIs).
- `ImageOutput` protocol: implement to add new image output strategies.
- `ConversionOptions`: frozen dataclass; use `dataclasses.replace` to create variants.
