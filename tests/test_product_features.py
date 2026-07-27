import json
from pathlib import Path

import pytest

import api
import batch
from batch import convert_batch, expand_inputs, output_for
from html_transform import DocumentTarget, prepare_document, rewrite_css_urls
from images import ImageIndex, ImageReference
from model import ConversionOptions, ConversionResult, ConversionWarning
from report import write_html_report


class Item:
    def __init__(self, name: str) -> None:
        self.name = name

    def get_name(self) -> str:
        return self.name


def test_content_selection_and_resource_policies_transform_output() -> None:
    content = '<body><section epub:type="appendix">remove</section><math>x</math><svg></svg><p>keep</p></body>'
    result, _ = prepare_document(
        Item("text/chapter.xhtml"),
        content,
        {"text/chapter.xhtml": DocumentTarget("chapter", {})},
        ImageIndex(),
        False,
        False,
        False,
        frozenset({"appendices"}),
        "omit",
        "omit",
    )

    assert "remove" not in result
    assert "<math" not in result and "<svg" not in result
    assert "keep" in result


def test_css_urls_are_rewritten_from_the_registered_asset_index() -> None:
    index = ImageIndex()
    index.add(ImageReference("images/cover.png", "assets/cover.png"))

    assert "assets/cover.png" in rewrite_css_urls(
        ".cover { background: url('../images/cover.png'); }", "styles/book.css", index
    )


def test_batch_expands_directories_and_isolates_individual_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good, bad = tmp_path / "good.epub", tmp_path / "bad.epub"
    good.write_bytes(b"")
    bad.write_bytes(b"")
    template = ConversionOptions(good, tmp_path / "ignored.html")

    def fake_convert(options: ConversionOptions) -> ConversionResult:
        if options.input_path == bad:
            raise ValueError("bad book")
        return ConversionResult(options.output_path, None, 1, 0, 0, 0, 0, (), 0, False, False)

    monkeypatch.setattr(batch, "convert_request", fake_convert)
    result = convert_batch((tmp_path,), template, tmp_path / "out")

    assert expand_inputs((tmp_path,)) == (bad.resolve(), good.resolve())
    assert result.succeeded == 1 and result.failed == 1
    assert output_for(good, tmp_path / "out") == tmp_path / "out" / "good.html"


def test_batch_accepts_worker_backend_parameter(tmp_path: Path) -> None:
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"")
    template = ConversionOptions(bad, tmp_path / "ignored.html")

    # workers=1 should ignore worker_backend and run sequentially.
    result = convert_batch(
        (tmp_path,), template, tmp_path / "out", workers=1, worker_backend="process"
    )
    assert result.failed >= 1


def test_batch_rejects_invalid_worker_backend(tmp_path: Path) -> None:
    template = ConversionOptions(tmp_path / "x.epub", tmp_path / "ignored.html")
    with pytest.raises(ValueError, match="worker_backend"):
        convert_batch((tmp_path,), template, tmp_path / "out", workers=2, worker_backend="invalid")  # type: ignore[arg-type]


def test_batch_rejects_zero_workers(tmp_path: Path) -> None:
    template = ConversionOptions(tmp_path / "x.epub", tmp_path / "ignored.html")
    with pytest.raises(ValueError, match="workers must be at least"):
        convert_batch((tmp_path,), template, tmp_path / "out", workers=0)


def test_library_api_replaces_only_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: list[ConversionOptions] = []

    def fake_convert(options: ConversionOptions) -> ConversionResult:
        captured.append(options)
        return ConversionResult(options.output_path, None, 0, 0, 0, 0, 0, (), 0, False, False)

    monkeypatch.setattr(api, "_convert", fake_convert)
    policy = ConversionOptions(tmp_path / "old.epub", tmp_path / "old.html", safe_html=True)

    api.convert(tmp_path / "new.epub", tmp_path / "new.html", policy)

    assert captured[0].input_path.name == "new.epub"
    assert captured[0].safe_html


def test_html_report_contains_chapters_and_warnings(tmp_path: Path) -> None:
    report_path = tmp_path / "report.html"
    result = ConversionResult(
        tmp_path / "book.html",
        None,
        1,
        0,
        0,
        0,
        0,
        (ConversionWarning("unresolved-image", "Missing cover", "chapter.xhtml"),),
        0,
        False,
        False,
        output_bytes=42,
        chapters=("chapter.xhtml",),
    )

    write_html_report(report_path, result)

    content = report_path.read_text(encoding="utf-8")
    assert "chapter.xhtml" in content and "Missing cover" in content


def test_json_report_includes_peak_memory(tmp_path: Path) -> None:
    from report import write_json_report as write_report

    report_path = tmp_path / "report.json"
    result = ConversionResult(
        tmp_path / "book.html",
        None,
        1,
        0,
        0,
        0,
        0,
        (),
        0.5,
        False,
        False,
        input_bytes=100,
        output_bytes=200,
        peak_memory_bytes=65536,
    )
    options = ConversionOptions(tmp_path / "book.epub", tmp_path / "book.html")

    write_report(report_path, result, options)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["peak_memory_bytes"] == 65536
