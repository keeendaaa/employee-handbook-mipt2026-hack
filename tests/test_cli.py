"""CLI errors and corpus consistency, without loading a model."""

from pathlib import Path
import json
import sys
from types import SimpleNamespace

from docx import Document
import pytest

from navigator.cli import parser, run


class BrokenEmbedder:
    def __init__(self, path):
        raise RuntimeError("synthetic offline model unavailable")


def test_index_failure_is_error_and_not_published(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    doc = Document()
    doc.add_paragraph("Синтетическое содержание")
    doc.save(raw / "synthetic.docx")
    monkeypatch.setitem(sys.modules, "navigator.ingest.embedding", SimpleNamespace(LocalEmbedder=BrokenEmbedder))
    monkeypatch.setattr("navigator.cli.get_store", lambda: SimpleNamespace(init_schema=lambda: None))
    out = tmp_path / "out"
    with pytest.raises(RuntimeError):
        run(parser().parse_args(["ingest", "--input", str(raw), "--output", str(out)]))
    report = json.loads((out / "report.json").read_text())
    assert report["status"] == "error"
    assert report["extraction_status"] == "complete"
    assert report["index_error"] == "RuntimeError"
    assert report["published"] is False


def test_search_reports_snapshot_used_even_if_index_switches(monkeypatch, capsys):
    embedder = SimpleNamespace(revision="test", encode=lambda *a, **k: [[1.0] * 384])
    monkeypatch.setitem(sys.modules, "navigator.ingest.embedding", SimpleNamespace(LocalEmbedder=lambda p: embedder))
    store = SimpleNamespace(
        active_revision=lambda: {"corpus_key": "old", "model_revision": "test"},
        search=lambda *a, **k: [{"corpus_revision": "new", "text": "Синтетический пример"}],
    )
    monkeypatch.setattr("navigator.cli.get_store", lambda: store)
    assert run(parser().parse_args(["search", "синтетический вопрос", "--baseline"])) == 0
    assert json.loads(capsys.readouterr().out)["corpus_revision"] == "new"
