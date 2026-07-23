# EPUB to HTML Converter

A Python command-line tool that converts an EPUB into one HTML document. It keeps
spine order when available, rewrites EPUB-internal links to work after merging, and
either embeds images for a portable single file or extracts them beside the HTML.

## Trust and safety

EPUB files are ZIP archives containing HTML, CSS, metadata, and images. By default,
the converter preserves source markup for fidelity. Treat the resulting HTML as
active content and use it only with EPUBs you understand and trust.

If you do not trust an EPUB or its source, pass `--safe-mode`. Safe mode removes active
elements, event handlers, inline CSS, SVG/XML, unsafe URL schemes, and external image/resource
loads before content is emitted. Normal reading markup, headings, tables, footnotes, navigation
links, and supported raster images are preserved where possible.

Safe mode validates embedded and extracted raster image signatures and excludes SVG. EPUB-originated
`<style>` elements and `style` attributes are removed; a file supplied with `--css` is explicitly
trusted local input and is inlined unchanged.

## Run from the checkout (recommended)

### Prerequisites

- Python 3.12 or higher

### Setup

1. **Create a virtual environment** (recommended):

    ```bash
    # Create the venv in the project folder
    py -3 -m venv .venv
    ```

    Activate using the command appropriate for your shell/OS:
    - **Windows - PowerShell**

        ```powershell
        .\.venv\Scripts\Activate.ps1
        ```

    - **Windows - Command Prompt (cmd.exe)**

        ```cmd
        .\.venv\Scripts\activate.bat
        ```

    - **Unix‑style shells** (Linux, macOS, WSL, Git‑bash, etc.)

        ```bash
        source .venv/bin/activate
        ```

2. **Install dependencies**:

    ```bash
    python -m pip install -r requirements.txt
    ```

3. Convert a book:

  ```bash
  python main.py "path/to/book.epub" -o output.html
  ```

This is the normal workflow.

### Optional installation

Installation is not required for local conversion. If desired, install the tool:

```bash
python -m pip install .
```

This creates the `epub-to-html` command. It is useful for invoking the converter
from any directory, automation or shell scripts, isolated virtual environments,
or other Python programs.

```bash
epub-to-html "path/to/book.epub" -o output.html
```

### Development tools

Install the project and development tools:

```bash
python -m pip install -e ".[dev]"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the canonical Nox commands used for
formatting, linting, type checks, and tests.

## Usage

### Basic Usage

Convert an EPUB to a single HTML file with embedded images:

```bash
python main.py "path/to/book.epub" -o output.html
```

### Command-Line Options and Examples

The following reference covers every option exposed by the CLI. `epub_path` is the required input
EPUB; `-h/--help` prints this reference.

| Option | Purpose | Example |
| --- | --- | --- |
| `epub_path` | Input EPUB file. | `python main.py "book.epub"` |
| `-h`, `--help` | Show help and exit. | `python main.py --help` |
| `-o`, `--output PATH` | Output HTML path; defaults to `output.html`. | `python main.py book.epub --output converted.html` |
| `-s`, `--strategy {embed,extract}` | Embed images as data URLs or extract them beside the HTML; defaults to `embed`. | `python main.py book.epub --strategy extract` |
| `-w`, `--wrap` | Add a complete HTML document shell and default styling. | `python main.py book.epub --wrap` |
| `-c`, `--css PATH` | Inline a trusted local stylesheet; also enables wrapping. | `python main.py book.epub --css styles.css` |
| `--remove-toc` | Remove detected table-of-contents elements. | `python main.py book.epub --remove-toc` |
| `--remove-cover` | Remove detected cover elements. | `python main.py book.epub --remove-cover` |
| `--images-dir-name NAME` | Extracted image directory basename; `{stem}` expands to the output filename stem. | `python main.py book.epub --strategy extract --images-dir-name assets` |
| `--chunked` | Write prepared documents incrementally to staging. | `python main.py book.epub --chunked` |
| `--safe-mode` | Remove active markup, unsafe URLs, EPUB CSS, SVG, and invalid raster images. | `python main.py book.epub --safe-mode --wrap` |
| `--force` | Replace existing HTML and extracted-image output. | `python main.py book.epub --force` |
| `--deadline-seconds N` | Cancel conversion after the cooperative deadline. | `python main.py book.epub --deadline-seconds 30` |
| `--fail-on-warning` | Abort without publishing if conversion warnings occur. | `python main.py book.epub --fail-on-warning` |
| `--no-validate-output` | Skip staged duplicate-ID and local-reference checks. | `python main.py book.epub --no-validate-output` |
| `--stable-mime-types` | Use known filename-extension MIME types instead of host-dependent MIME guessing. | `python main.py book.epub --stable-mime-types` |
| `--newline {lf,crlf}` | Select output line endings; defaults to `lf`. | `python main.py book.epub --newline crlf` |
| `--report-json PATH` | Write a local machine-readable conversion report. | `python main.py book.epub --report-json report.json` |
| `--no-progress` | Disable progress bars. | `python main.py book.epub --no-progress` |
| `--force-progress` | Show progress bars even when stderr is not a TTY. | `python main.py book.epub --force-progress` |
| `--verbose` | Show unexpected error tracebacks. | `python main.py book.epub --verbose` |
| `--max-archive-entries N` | Maximum ZIP member count; defaults to `10000`. | `python main.py book.epub --max-archive-entries 2000` |
| `--max-compressed-bytes N` | Maximum compressed archive size; defaults to `268435456`. | `python main.py book.epub --max-compressed-bytes 50000000` |
| `--max-expanded-bytes N` | Maximum expanded archive size; defaults to `1073741824`. | `python main.py book.epub --max-expanded-bytes 500000000` |
| `--max-entry-bytes N` | Maximum expanded size of one archive member; defaults to `104857600`. | `python main.py book.epub --max-entry-bytes 50000000` |
| `--max-compression-ratio N` | Maximum ZIP compression ratio; defaults to `1000`. | `python main.py book.epub --max-compression-ratio 500` |
| `--max-documents N` | Maximum EPUB document items; defaults to `5000`. | `python main.py book.epub --max-documents 1000` |
| `--max-images N` | Maximum EPUB image items; defaults to `10000`. | `python main.py book.epub --max-images 2000` |
| `--max-output-bytes N` | Maximum generated output size; defaults to `1073741824`. | `python main.py book.epub --max-output-bytes 500000000` |

### Safe mode for untrusted EPUBs

Normal conversion preserves source markup and is intended for EPUBs you understand
and trust. For an EPUB from an unknown source, explicitly enable safe mode:

```bash
python main.py "unknown-source.epub" --safe-mode --wrap -o "output.html"
```

Safe mode strips browser-active markup and unsafe resource URLs. It is a content
filter, not a complete sandbox.

## License

See [LICENSE](LICENSE) file for details.
