from bs4 import BeautifulSoup

from html_transform import DocumentTarget, build_targets, prepare_document, sanitize, wrap_html
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


def test_queries_are_preserved_while_local_fragments_are_rewritten() -> None:
    targets = {
        "text/a.xhtml": DocumentTarget("epub-a", {}),
        "text/b.xhtml": DocumentTarget("epub-b", {"end": "epub-b--end"}),
    }
    content = (
        '<body><a href="b.xhtml#end">local</a><a href="b.xhtml?edition=2#end">query</a></body>'
    )

    result, _ = prepare_document(
        Item("text/a.xhtml"), content, targets, ImageIndex(), False, False, False
    )

    assert 'href="#epub-b--end"' in result
    assert 'href="b.xhtml?edition=2#end"' in result


def test_targets_add_stable_hashes_for_unicode_slug_collisions() -> None:
    first = build_targets([(Item("text/Å.xhtml"), '<p id="Å">one</p>')])
    second = build_targets([(Item("text/Å.xhtml"), '<p id="Å">one</p>')])

    target = first["text/Å.xhtml"]
    assert target == second["text/Å.xhtml"]
    assert target.anchor.startswith("epub-text-xhtml-")
    assert target.ids["Å"].startswith(f"{target.anchor}--item-")
