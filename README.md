# EPUB to HTML Converter

A Python command-line tool that converts an EPUB into one HTML document. It keeps
spine order when available, rewrites EPUB-internal links to work after merging, and
either embeds images for a portable single file or extracts them beside the HTML.

## Trust and safety

EPUB files are ZIP archives containing HTML, CSS, metadata, and images. By default,
the converter preserves source markup for fidelity. Treat the resulting HTML as
active content and use it only with EPUBs you understand and trust.

If you do not trust an EPUB or its source, pass `--safe-mode`. Safe mode removes active
elements, event handlers, inline CSS, SVG/XML, unsafe URL schemes, and external
image/resource loads before content is emitted. Normal reading markup, headings,
tables, footnotes, navigation links, and supported raster images are preserved
where possible.

## Run from the checkout (recommended)

### Prerequisites

- Python 3.12 or higher

### Setup Steps

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
or other Python programs. For a one-off conversion in this checkout, use
`python main.py` instead.

### Development tools

Install development tools for formatting, type checking, and tests:

```bash
python -m pip install -r dev-requirements.txt
```

## Usage

### Basic Usage

Convert an EPUB file to HTML with embedded images (default behavior):

```bash
python main.py "path/to/book.epub"
```

Output: `output.html` (resolved to absolute path in current directory)

### Command-Line Options

```text
usage: main.py [options] epub_path

positional arguments:
  epub_path                   Path to the input EPUB file

optional arguments:
  -h, --help                  Show this help message and exit
  -o, --output PATH           Path to output HTML file. Relative paths are resolved from the current working directory and normalized to absolute paths. Default: output.html
  -s, --strategy STRATEGY     Image handling strategy: 'embed' embeds images as base64 data URLs (compact HTML, all in one file); 'extract' saves images as separate files (default: embed)
  -w, --wrap                  Wrap content in complete HTML structure with default styling
  -c, --css PATH              Path to a CSS file whose contents will be inlined into a <style> tag; implies --wrap
  -v, --verbose               Enable verbose logging (DEBUG level); shorthand for --log-level DEBUG
  --no-progress               Disable progress bars for long-running operations
  --allow-unknown-mime        Allow images with unknown MIME types; when enabled and media type cannot be determined, images will be skipped (use --strategy extract instead)
  --remove-toc                Remove table of contents elements (default: preserve TOC and rewrite internal links)
  --remove-cover              Remove cover page elements (default: preserve cover)
  --images-dir-name NAME      Directory name pattern for extracted images when using --strategy extract. Use {stem} as placeholder for HTML filename stem (default: {stem}_files)
  --force-progress            Force progress bars even when stderr is not a TTY; useful for CI logs (respects --no-progress if set)
  --chunked                   Process documents incrementally to reduce peak memory for very large EPUBs
    --safe-mode                 Sanitize active HTML/CSS and unsafe resource URLs; use for untrusted EPUBs
  --force                     Replace existing output and extracted-image directories
  --max-archive-entries N     Maximum ZIP members (default: 10000)
  --max-compressed-bytes N    Maximum compressed archive bytes (default: 268435456)
  --max-expanded-bytes N      Maximum expanded archive bytes (default: 1073741824)
  --max-entry-bytes N         Maximum expanded bytes per archive member (default: 104857600)
  --max-compression-ratio N   Maximum member compression ratio (default: 1000)
  --max-documents N           Maximum EPUB document items (default: 5000)
  --max-images N              Maximum EPUB image items (default: 10000)
  --max-output-bytes N        Maximum generated HTML bytes (default: 1073741824)
  --log-level LEVEL           Set logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: DEBUG if -v/--verbose, else INFO)
  --log-format FORMAT         Set logging message format (default: '- %(message)s')
```

### Examples

**Embed all images as base64 (compact HTML file, default)**:

```bash
python main.py "book.epub" -o "output.html"
```

Output: `output.html` in current directory. The script logs the absolute path of the output file, but the actual file is created using the path provided. All images embedded as data URLs.

**Embed images but allow unknown MIME types**:

```bash
python main.py "book.epub" -o "output.html" --allow-unknown-mime
```

**⚠️ Note**: When `--allow-unknown-mime` is enabled and a media type cannot be determined, the image will be skipped instead of embedding. For reliable image handling, use `--strategy extract` instead to save images as separate files.

**Extract images to separate files with relative output path**:

```bash
python main.py "book.epub" -o "output.html" -s extract
```

Creates in current directory:

- `output.html` - the HTML file
- `output_files/` - folder containing extracted images (default directory name)
- Images are referenced with relative paths: `output_files/image_name.ext`

**Extract images with custom directory name**:

```bash
python main.py "book.epub" -o "output.html" -s extract --images-dir-name "images"
```

Creates:

- `output.html` - the HTML file
- `images/` - folder containing extracted images
- Images are referenced with relative paths: `images/image_name.ext`

**Extract images using an absolute path**:

```bash
python main.py "book.epub" -o "/home/user/output.html" -s extract
```

Creates:

- `/home/user/output.html` - the HTML file
- `/home/user/output_files/` - folder containing extracted images
- Images are referenced with relative paths: `output_files/image_name.ext`

**Windows PowerShell example with extract strategy**:

```powershell
python main.py "C:\Users\Books\book.epub" -o "C:\Output\book.html" -s extract
```

Creates:

- `C:\Output\book.html` - the HTML file
- `C:\Output\book_files\` - folder containing extracted images
- Logs display absolute paths; the actual output uses the path provided

**POSIX shell example with extract strategy**:

```bash
python main.py "/home/user/book.epub" -o "/tmp/output.html" -s extract
```

Creates:

- `/tmp/output.html` - the HTML file
- `/tmp/output_files/` - folder containing extracted images

**Remove the table of contents**:

```bash
python main.py "book.epub" -o "output.html" --remove-toc
```

Removes EPUB navigation and table-of-contents elements from the output. Internal links are preserved when the table of contents is not removed.

**Remove the cover page**:

```bash
python main.py "book.epub" -o "output.html" --remove-cover
```

Removes cover-page elements identified by common EPUB cover markers.

**Wrap in HTML structure with default styling**:

```bash
python main.py "book.epub" -w -o "output.html"
```

Output: Complete HTML5 document with DOCTYPE, head, and body tags, including default CSS styling for readability.

**Use custom CSS file** (implies `--wrap`):

```bash
python main.py "book.epub" -c "styles.css" -o "output.html"
```

Inlines the CSS from `styles.css` into a `<style>` tag and automatically wraps the content in a complete HTML structure. The `-c/--css` option always implies `--wrap`, so you don't need to specify both.

**Enable debug logging with custom format**:

```bash
python main.py "book.epub" -v -o "output.html"
```

Shows DEBUG-level log messages. Use `--log-level` to set a different level:

```bash
python main.py "book.epub" --log-level WARNING -o "output.html"
```

**Force progress bars in CI/non-TTY environment**:

```bash
python main.py "book.epub" --force-progress -o "output.html"
```

By default, progress bars are disabled when running in non-interactive environments. Use `--force-progress` to enable them in CI logs.

**Process a very large EPUB incrementally**:

```bash
python main.py "large-book.epub" --chunked -o "output.html"
```

Use this mode when memory is limited or the book has thousands of pages. It processes
each source document independently before merging the results. For ordinary books,
the default mode is usually simpler and just as fast.

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
