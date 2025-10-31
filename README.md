# EPUB to HTML Converter

A Python script that converts EPUB files to single HTML files with image handling and optional HTML structuring.

## Installation

### Prerequisites

- Python 3.12 or higher

### Setup Steps

1. **Create a virtual environment** (recommended):

   ```bash
   # Create venv in the project folder
   py -3 -m venv .venv
   
   # Activate (PowerShell)
   .\.venv\Scripts\Activate.ps1
   
   # Activate (Command Prompt)
   .\.venv\Scripts\activate.bat
   
   # Activate (bash/git-bash)
   source .venv/Scripts/activate
   ```

2. **Install dependencies**:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. **Optional: Install development tools** (for code quality checks):

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
usage: main.py [-h] [-o OUTPUT] [-s {embed,extract}] [-w] [-c CSS] [-v] [--no-progress] [--allow-unknown-mime] [--keep-toc] [--keep-cover] [--images-dir-name NAME] [--force-progress] [--log-level LEVEL] [--log-format FORMAT] epub_path

positional arguments:
  epub_path                 Path to the input EPUB file

optional arguments:
  -h, --help                Show this help message and exit
  -o, --output PATH         Path to output HTML file. Relative paths are resolved from the current working directory and normalized to absolute paths. Default: output.html
  -s, --strategy STRATEGY   Image handling strategy: 'embed' embeds images as base64 data URLs (compact HTML, all in one file); 'extract' saves images as separate files (default: embed)
  -w, --wrap                Wrap content in complete HTML structure with default styling
  -c, --css PATH            Path to a CSS file whose contents will be inlined into a <style> tag; implies --wrap
  -v, --verbose             Enable verbose logging (DEBUG level); shorthand for --log-level DEBUG
  --no-progress             Disable progress bars for long-running operations
  --allow-unknown-mime      Allow images with unknown MIME types; when enabled and media type cannot be determined, images will be skipped (use --strategy extract instead)
  --keep-toc                Preserve table of contents elements instead of removing them (default: remove)
  --keep-cover              Preserve cover page elements instead of removing them (default: remove)
  --images-dir-name NAME    Directory name pattern for extracted images when using --strategy extract. Use {stem} as placeholder for HTML filename stem (default: {stem}_files)
  --force-progress          Force progress bars even when stderr is not a TTY; useful for CI logs (respects --no-progress if set)
  --log-level LEVEL         Set logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: DEBUG if -v/--verbose, else INFO)
  --log-format FORMAT       Set logging format (default: '%(asctime)s - %(levelname)s - %(message)s')
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

**Preserve table of contents and cover**:

```bash
python main.py "book.epub" --keep-toc --keep-cover -o "output.html"
```

By default, TOC and cover elements are removed. Use these flags to preserve them.

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

## License

See [LICENSE](LICENSE) file for details.
