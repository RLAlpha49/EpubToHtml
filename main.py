import warnings
import ebooklib
from ebooklib import epub
import os
import argparse
import base64
import re

# Ignore UserWarning from ebooklib
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib.epub")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib.epub")


def epub_to_html(epub_path, html_path):
    book = epub.read_epub(epub_path)
    html_content = ""
    img_tags = {}

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            img_data = base64.b64encode(item.get_content()).decode("utf-8")
            img_tags[item.get_name()] = (
                f'<img src="data:image/{item.media_type.split("/")[-1]};base64,{img_data}" style="max-width: 100%; '
                f'height: auto;">'
            )

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content().decode("utf-8")
            for img_name, img_tag in img_tags.items():
                content = re.sub(
                    r'src=["\'].*?' + re.escape(img_name) + ".*?[\"'].*?>",
                    img_tag,
                    content,
                )
            html_content += content

    with open(html_path, "w", encoding="utf-8") as html_file:
        html_file.write(html_content)


parser = argparse.ArgumentParser(description="Convert an epub file to a single html file.")
parser.add_argument("epub_path", type=str, help="The path to the epub file.")
parser.add_argument(
    "--html_path",
    type=str,
    default=os.getcwd() + "/output.html",
    help="The path to the output html file. Default is current directory.",
)

args = parser.parse_args()

epub_to_html(args.epub_path, args.html_path)
