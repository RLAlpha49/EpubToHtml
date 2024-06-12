# EPUB to HTML Converter

This Python script converts an EPUB file into a single HTML file. It also handles images in the EPUB file by converting them into Data URLs and embedding them directly into the HTML content. The script also applies some basic CSS to the images to ensure they fit within the width of the page.

## How it Works

The script uses the `ebooklib` library to read the EPUB file. It iterates over all the items in the EPUB file, and if an item is an image, it converts the image into a Data URL and stores it in a dictionary with the image's name as the key.

Then, the script iterates over the items in the EPUB file again, and if an item is a document, it gets the content of the document and replaces any image references with the corresponding Data URL from the dictionary. The modified content is then added to the HTML content.

Finally, the HTML content is written to an output file.

## Usage

You can run the script from the command line with the following command:

```bash
python main.py <epub_path> --html_path <html_path>
```

Replace `<epub_path>` with the path to the EPUB file you want to convert, and replace `<html_path>` with the path where you want the output HTML file to be saved. If you don't provide a path for the output file, it will be saved as output.html in the current directory.

## Poetry

This project uses Poetry for dependency management. If you don't have Poetry installed, you can install it with the following command:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

or on Windows:

```bash
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

Then, you can install the dependencies for this project with the following command:

```bash
poetry install
```

This will create a virtual environment and install the dependencies specified in the pyproject.toml file.  To run the script within the Poetry environment, you can use the following command:

```bash
poetry run python main.py <epub_path> --html_path <html_path>
```

Replace `<epub_path>` and `<html_path>` as described in the Usage section above.