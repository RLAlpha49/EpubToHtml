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
| `epub_path` | Input EPUB file or directory containing EPUB files. | `python main.py "book.epub"` |
| `-h`, `--help` | Show help and exit. | `python main.py --help` |
| `--version` | Show the installed tool version and exit. | `epub-to-html --version` |
| `--print-completion {bash,zsh,fish,powershell}` | Print a complete shell-completion script and exit; it does not modify shell configuration automatically. | `epub-to-html --print-completion powershell` |
| `-o`, `--output PATH` | Output HTML file for one EPUB, or output directory for an EPUB directory. Defaults to `output.html` for a file and `output` for a directory. | `python main.py book.epub --output converted.html` |
| `--workers N` | Maximum directory-input workers; defaults conservatively to `1`. | `python main.py books --output converted --workers 2` |
| `--inspect` | Print EPUB metadata, spine, media inventory, layout signals, and unsupported features without writing output. | `python main.py book.epub --inspect` |
| `-s`, `--strategy {embed,extract}` | Embed images as data URLs or extract them beside the HTML; defaults to `embed`. | `python main.py book.epub --strategy extract` |
| `-w`, `--wrap` | Add a complete HTML document shell and default styling. It is optional when using any option that needs wrapped output. | `python main.py book.epub --wrap` |
| `-c`, `--css PATH` | Inline a trusted local stylesheet; automatically enables wrapping. | `python main.py book.epub --css styles.css` |
| `--remove-toc` | Remove detected table-of-contents elements. | `python main.py book.epub --remove-toc` |
| `--remove-cover` | Remove detected cover elements. | `python main.py book.epub --remove-cover` |
| `--spine-range START:END` | Convert a one-based inclusive chapter range; either bound may be omitted. | `python main.py book.epub --spine-range 2:8` |
| `--exclude-content CATEGORY` | Exclude `cover`, `navigation`, `front-matter`, `endnotes`, or `appendices`; repeatable. | `python main.py book.epub --exclude-content appendices` |
| `--images-dir-name NAME` | Extracted image directory basename; `{stem}` expands to the output filename stem. | `python main.py book.epub --strategy extract --images-dir-name assets` |
| `--chunked` | Write prepared documents incrementally to staging; navigation requires collecting the generated sections first. | `python main.py book.epub --chunked` |
| `--safe-mode` | Remove active markup, unsafe URLs, EPUB CSS, SVG, and invalid raster images. | `python main.py book.epub --safe-mode --wrap` |
| `--preserve-internal-css` | Inline EPUB stylesheets and rewrite their registered local asset URLs; ignored by safe mode. | `python main.py book.epub --preserve-internal-css --wrap` |
| `--svg-policy {omit,extract,preserve}` | Select SVG handling; safe mode always removes SVG. | `python main.py book.epub --svg-policy preserve` |
| `--mathml-policy {omit,preserve}` | Select MathML handling; safe mode remains restrictive. | `python main.py book.epub --mathml-policy preserve` |
| `--media-policy {omit,extract,preserve}` | Choose audio/video resource treatment. Extraction copies resources only with `--strategy extract`. | `python main.py book.epub --strategy extract --media-policy extract` |
| `--font-policy {omit,extract,preserve}` | Choose embedded-font resource treatment. Extraction copies resources only with `--strategy extract`. | `python main.py book.epub --strategy extract --font-policy extract` |
| `--navigation` | Add an automatically generated table of contents and back-to-top links; automatically enables wrapping. | `python main.py book.epub --navigation` |
| `--navigation-depth N` | Include headings through level `N` in generated navigation (`1`–`6`); defaults to `1`. | `python main.py book.epub --navigation --navigation-depth 2` |
| `--reader-theme {auto,light,dark}` | Select the wrapped reader color theme; defaults to `auto`. | `python main.py book.epub --reader-theme dark --wrap` |
| `--reader-max-width CSS_VALUE` | Set wrapped reading width and automatically enable wrapping; defaults to `72ch` when wrapping is enabled. | `python main.py book.epub --reader-max-width 65ch` |
| `--reader-font-family CSS_VALUE` | Set wrapped reading font and automatically enable wrapping; defaults to `Georgia, serif` when wrapping is enabled. | `python main.py book.epub --reader-font-family system-ui` |
| `--force` | Replace existing HTML and extracted-image output. | `python main.py book.epub --force` |
| `--deadline-seconds N` | Cancel conversion after the cooperative deadline. | `python main.py book.epub --deadline-seconds 30` |
| `--fail-on-warning` | Abort without publishing if conversion warnings occur. | `python main.py book.epub --fail-on-warning` |
| `--no-validate-output` | Skip staged duplicate-ID and local-reference checks. | `python main.py book.epub --no-validate-output` |
| `--stable-mime-types` | Use known filename-extension MIME types instead of host-dependent MIME guessing. | `python main.py book.epub --stable-mime-types` |
| `--newline {lf,crlf}` | Select output line endings; defaults to `lf`. | `python main.py book.epub --newline crlf` |
| `--report-json PATH` | Write a local machine-readable conversion report. | `python main.py book.epub --report-json report.json` |
| `--report-html PATH` | Write a companion HTML report with chapters, warnings, and output facts. | `python main.py book.epub --report-html report.html` |
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

### Shell completion

Completion output is intentionally printed rather than silently editing a shell
profile. Each generated script covers every CLI option, choice value,
and the EPUB positional file. Install it once using the command appropriate for
your shell, then completion is automatic in future sessions:

- **PowerShell:** `epub-to-html --print-completion powershell | Out-File $PROFILE\u005cepub-to-html.ps1 -Encoding utf8`, then add `. $PROFILE\u005cepub-to-html.ps1` to your profile.
- **Bash:** `epub-to-html --print-completion bash > ~/.local/share/bash-completion/completions/epub-to-html`, then start a new shell.
- **Zsh:** `epub-to-html --print-completion zsh > ~/.zfunc/_epub-to-html`, and add that directory to `fpath`.
- **Fish:** `epub-to-html --print-completion fish > ~/.config/fish/completions/epub-to-html.fish`.

The converter itself does not need a completion script to run; this is only shell
help for typing commands.

## Library use

Python integrations can call the documented library API without subprocesses:

```python
from api import convert
from model import ConversionOptions

result = convert("book.epub", "book.html", ConversionOptions(
    input_path="unused.epub", output_path="unused.html", safe_html=True
))
print(result.output_path)
```

The explicit path arguments always win; the supplied `ConversionOptions` contributes
only conversion policy. `ConversionResult` supplies paths, counts, warnings, duration,
and selected chapter names.

## Output behavior and limitations

The converter reads EPUB document items in spine order when the EPUB supplies a
spine; otherwise it uses the document order provided by the publication. It gives
each merged section and source ID a deterministic unique anchor, then rewrites
resolvable local document links to those anchors. Links with query strings,
external URLs, root-relative URLs, and unresolved paths remain unchanged so the
conversion does not silently invent a destination.

Image references are resolved against their EPUB-relative paths. Ambiguous image
basenames are deliberately not guessed and produce a warning. UTF-8 is preferred
for chapter text; when it fails, the converter samples up to 64 KiB for encoding
detection and records a `decode-fallback` warning.

This tool targets reflowable, HTML-based EPUB content. Fixed-layout publications,
complex CSS layouts, JavaScript-driven books, audio/video, fonts, SVG, MathML,
form controls, and non-image assets are not faithfully preserved. Safe mode
intentionally removes SVG, MathML, CSS, active elements, and unsafe URLs. For
trusted EPUBs, normal mode preserves more source markup but does not guarantee
that the source will render identically outside its original reader.

### Portability and file size

`--strategy embed` is the default. It produces one self-contained HTML file that
is easy to move or share, but base64-encoded images can make it substantially
larger. `--strategy extract` keeps the HTML smaller by writing an image directory
beside it. Keep that directory and the HTML together when moving, copying, or
publishing the result; the generated references are relative paths.

### Limits and conversion warnings

Before parsing, the converter rejects archives that exceed its entry, compressed
size, expanded size, member size, compression ratio, document, image, or output
size limits. The defaults are listed in `--help` and can be made stricter or
looser with the corresponding `--max-*` options. A deadline can be supplied with
`--deadline-seconds`; output is staged and published only after conversion checks
complete.

Warnings cover skipped images/documents, ambiguous or unresolved images, and
encoding fallbacks. Use `--fail-on-warning` to prevent publication when any
warning occurs, or `--report-json report.json` to save the full warning
list, paths, counts, sizes, duration, conversion policy, and tool version for automation.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Conversion completed successfully. |
| `1` | Invalid input or another expected conversion failure. |
| `2` | Invalid command-line usage (reported by `argparse`). |
| `3` | Unexpected internal failure; use `--verbose` for a traceback. |
| `4` | Policy or staged-output validation rejection, including archive limits. |
| `5` | Output or report write failure. |
| `130` | Conversion was cancelled or exceeded its deadline. |

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| “Input is not a valid ZIP/EPUB” or missing container files | Confirm the path points to a complete EPUB, not a renamed download, and try opening it in a standard EPUB reader. |
| Images are missing | Review conversion warnings. Verify that the EPUB manifest contains the image and that its relative path is unambiguous. For extracted output, keep the generated asset directory with the HTML. |
| A local link does not work | Only resolvable, query-free EPUB-local links are rewritten. Check the warning report and whether the target source document or fragment exists. |
| Garbled characters | Look for a `decode-fallback` warning. The source may declare or contain an incorrect encoding |
| HTML is unexpectedly large | Use `--strategy extract`, remove unneeded cover/TOC content, or inspect large images in the source EPUB. Embedded images make the single output portable at the cost of size. |
| “Output already exists” or access denied | Pick a new path or use `--force` only when replacement is intended. Ensure the output directory is writable. |
| Windows path or filename error | Use a valid filename and a safe `--images-dir-name` basename; avoid `..`, separators, and device names such as `CON` or `LPT1`. |
| File is locked by antivirus, sync, or another application | Close browser/editor windows holding the output, pause the interfering process if appropriate, and retry in a local writable directory. |

## Testing and contributing

The project uses Nox for repeatable development commands. After installing the
development extras, run `python -m nox` to format, lint, type-check, test, and
build the project. To run one activity, use `python -m nox -- tests`,
`python -m nox -- lint`, or another task listed in [CONTRIBUTING.md](CONTRIBUTING.md).
The test suite covers archive policy, conversion transforms, image handling,
output staging, and CLI behavior. Contributions should include a focused regression
test when they change observable conversion behavior.

## License

See [LICENSE](LICENSE) file for details.
