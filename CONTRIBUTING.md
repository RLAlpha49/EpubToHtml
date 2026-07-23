# Contributing

## Development setup

Use Python 3.12 or 3.13. Install the complete local toolchain with:

```bash
python -m pip install -e ".[dev]"
```

## Canonical commands

Nox is the project command interface on every platform:

- `python -m nox -s format` checks formatting.
- `python -m nox -s lint` runs Ruff lint rules.
- `python -m nox -s typecheck` runs mypy using the committed EbookLib stubs.
- `python -m nox -s tests` runs pytest on supported Python versions.
- `python -m nox -s build` builds a wheel, installs it, and checks `epub-to-html --help`.

Run `python -m nox` before opening a pull request.
