from bs4 import BeautifulSoup

from html_transform import DocumentTarget, prepare_document, sanitize, wrap_html
from images import ImageIndex


class Item:
    def __init__(self, name: str) -> None:
        self.name = name

    def get_name(self) -> str:
        return self.name


def test_preparation_namespaces_ids_rewrites_forward_links_and_filters_locally() -> None:
    targets = {
        "text/a.xhtml": DocumentTarget("epub-a", {"same": "epub-a--same"}),
        "text/b.xhtml": DocumentTarget("epub-b", {"end": "epub-b--end"}),
    }
    content = (
        '<body><nav class="toc">remove</nav><p id="same"><a href="b.xhtml#end">next</a></p></body>'
    )

    result, warnings = prepare_document(
        Item("text/a.xhtml"), content, targets, ImageIndex(), True, False, False
    )

    assert 'id="epub-a--same"' in result
    assert 'href="#epub-b--end"' in result
    assert "remove" not in result
    assert warnings == []


def test_sanitizer_removes_active_content_and_unsafe_urls() -> None:
    soup = BeautifulSoup(
        '<script>x</script><img onerror="x" src="javascript:x"><a href="javascript:x">x</a><p>safe</p>',
        "html.parser",
    )

    sanitize(soup)

    assert soup.find("script") is None
    image = soup.find("img")
    link = soup.find("a")
    paragraph = soup.find("p")
    assert image and image.attrs == {}
    assert link and link.get("href") is None
    assert paragraph and paragraph.text == "safe"


def test_wrapped_title_is_escaped() -> None:
    html = wrap_html("content", "</title><script>alert(1)</script>", None)

    assert "&lt;/title&gt;" in html
    assert "<title></title>" not in html
