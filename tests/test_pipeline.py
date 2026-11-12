"""Synthetic documents only: these tests do not assess the real corpus."""

import json
from pathlib import Path

from docx import Document
import pytest

from navigator.cli import parser, run
from navigator.ingest.chunking import chunk_document
from navigator.ingest.pipeline import extract_corpus, index_corpus
from navigator.ingest.pipeline import load_extraction


class CharacterTokenizer:
    def __call__(self, text, **kwargs):
        return {"offset_mapping": [(i, i + 1) for i in range(len(text))]}

    def encode(self, text):
        return [1] * (len(text) + 2)


class Embedder:
    tokenizer = CharacterTokenizer()
    revision = "synthetic-only"

    def encode(self, texts):
        assert all(len(self.tokenizer.encode("passage: " + t)) <= 512 for t in texts)
        return [[1.0] + [0.0] * 383 for _ in texts]


class Store:
    def __init__(self):
        self.calls = []

    def publish(self, documents, chunks, **kwargs):
        self.calls.append((documents, chunks, kwargs))
        return kwargs["corpus_key"]


def make_doc(path: Path, text="Синтетическое правило. Подайте тестовую заявку."):
    doc = Document()
    doc.add_heading("Синтетический регламент", level=1)
    doc.add_paragraph(text)
    doc.save(path)


def test_exact_slices_token_limit_and_stable_ids():
    text = "Пример с кириллицей и emoji 🧑‍💻. " * 90
    doc = {"document_id": "test", "version_id": "test-v1",
           "blocks": [{"text": text, "locator": {"block": 1}, "heading_path": ["Тест"]}]}
    chunks = chunk_document(doc, CharacterTokenizer(), "test-model")
    assert len(chunks) > 1
    assert "".join(c["text"] for c in chunks) == text
    assert all(c["text"] == text[c["start"]:c["end"]] for c in chunks)
    assert all(len(CharacterTokenizer().encode("passage: " + c["text"])) <= 512 for c in chunks)
    assert chunks == chunk_document(doc, CharacterTokenizer(), "test-model")
    assert chunks[0]["chunk_id"] != chunk_document(doc, CharacterTokenizer(), "new-model")[0]["chunk_id"]


def test_embedding_title_cannot_change_citation_or_exceed_token_budget():
    text = "Синтетическое положение. " * 60
    doc = {"document_id": "test", "version_id": "test-v1", "name": "Очень длинное название " * 100,
           "blocks": [{"text": text, "locator": {"page": 1}, "heading_path": ["Синтетический раздел"]}]}
    chunks = chunk_document(doc, CharacterTokenizer(), "test-model")
    assert "".join(c["text"] for c in chunks) == text
    assert all(c["embedding_text"].endswith(c["text"]) for c in chunks)
    assert all(len(CharacterTokenizer().encode("passage: " + c["embedding_text"])) <= 512 for c in chunks)


def test_extract_and_reimport_are_stable_and_changed_file_gets_new_version(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    source = raw / "synthetic.docx"
    make_doc(source)
    original = source.read_bytes()
    docs, report = extract_corpus(raw, out)
    assert report["status"] == "complete"
    again, _ = extract_corpus(raw, out)
    assert docs == again
    assert source.read_bytes() == original
    store = Store()
    key, count = index_corpus(docs, Embedder(), store)
    assert count > 0
    assert index_corpus(again, Embedder(), store)[0] == key
    make_doc(source, "Другое синтетическое правило.")
    changed, _ = extract_corpus(raw, out)
    assert changed[0]["document_id"] == docs[0]["document_id"]
    assert changed[0]["version_id"] != docs[0]["version_id"]
    assert len(list((out / "documents").glob("*.json"))) == 2


def test_bad_file_is_reported_without_discarding_good_file(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_doc(raw / "synthetic.docx")
    (raw / "broken.pdf").write_bytes(b"not a pdf")
    docs, report = extract_corpus(raw, tmp_path / "out")
    assert len(docs) == 1
    assert report["status"] == "error"
    assert report["published"] is False
    assert any(f["name"] == "broken.pdf" and f["status"] == "error" for f in report["files"])


def test_missing_manifest_file_and_hash_mismatch(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_doc(raw / "synthetic.docx")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"expected_count": 2, "files": [
        {"name": "missing.xlsx", "document_id": "D1"},
        {"name": "synthetic.docx", "document_id": "D2", "sha256": "wrong"},
    ]}))
    docs, report = extract_corpus(raw, tmp_path / "out", manifest=manifest)
    assert not docs
    assert report["status"] == "error"
    assert report["missing_files"] == ["missing.xlsx"]
    assert "SHA-256" in report["files"][0]["error"]


def test_cli_does_not_publish_failed_import(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "bad.pdf").write_bytes(b"bad")
    def reject_db():
        pytest.fail("БД не должна вызываться после ошибки извлечения")
    monkeypatch.setattr("navigator.cli.get_store", reject_db)
    assert run(parser().parse_args(["ingest", "--input", str(raw), "--output", str(tmp_path / "out")])) == 1


def test_cli_rejects_output_inside_originals(tmp_path):
    with pytest.raises(ValueError, match="отдельными"):
        run(parser().parse_args(["extract", "--input", str(tmp_path), "--output", str(tmp_path / "out")]))


def test_cached_extraction_rejects_changed_source_and_tampered_artifact(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    make_doc(raw / "synthetic.docx")
    docs, _ = extract_corpus(raw, out)
    assert load_extraction(out / "report.json", raw)[0] == docs
    artifact = out / "documents" / (docs[0]["version_id"] + ".json")
    tampered = dict(docs[0], warnings=["Подменено"])
    artifact.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="не совпадает"):
        load_extraction(out / "report.json", raw)
    artifact.write_text(json.dumps(docs[0]))
    make_doc(raw / "synthetic.docx", "Другой текст")
    with pytest.raises(ValueError, match="изменился"):
        load_extraction(out / "report.json", raw)
