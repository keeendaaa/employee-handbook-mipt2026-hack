"""The reader exposes an immutable extraction, never ingestion file paths."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from navigator.api import create_app


def test_document_reader_returns_all_blocks_and_only_public_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv('MATERIAL_REQUEST_DB', str(tmp_path / 'requests.sqlite'))
    doc = {'document_id': 'synthetic', 'version_id': 'a' * 64, 'sha256': 'b' * 64,
           'name': 'Синтетический регламент', 'warnings': ['OCR требует проверки'],
           'path': '/private/ingest/source.pdf', 'blocks': [
               {'text': 'Первая страница', 'locator': {'page': 1}, 'method': 'native',
                'internal_path': '/private/image.png'},
               {'text': 'Вторая страница', 'locator': {'page': 2}, 'method': 'ocr'}]}
    active = {'corpus_key': 'snapshot'}
    calls = []
    def get_document(document_id, corpus_key):
        calls.append((document_id, corpus_key))
        return doc if document_id == 'synthetic' else None
    store = SimpleNamespace(active_revision=lambda: active, document_in_corpus=get_document)
    with TestClient(create_app(service=SimpleNamespace(store=store))) as client:
        result = client.get('/api/documents/synthetic?corpus_revision=snapshot')
        assert result.status_code == 200
        assert [b['text'] for b in result.json()['blocks']] == ['Первая страница', 'Вторая страница']
        assert result.json()['warnings'] == doc['warnings']
        assert result.json()['version_id'] == doc['version_id']
        assert '/private' not in result.text
        assert calls == [('synthetic', 'snapshot')]
        assert client.get('/api/documents/synthetic?corpus_revision=stale').status_code == 409
        assert len(calls) == 1
        assert client.get('/api/documents/missing?corpus_revision=snapshot').status_code == 404
        assert client.get('/api/documents/synthetic').status_code == 422
        active = None
        assert client.get('/api/documents/synthetic?corpus_revision=snapshot').status_code == 503
