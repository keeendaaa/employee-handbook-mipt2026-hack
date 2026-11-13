"""Synthetic uploads and downloads; no external network or private material."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import httpcore
import pytest

from navigator.api import create_app
from navigator.imports.download import ImportFailure, PublicBackend, direct_link, download, filename, public_url


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://localhost/a.pdf', 'http://127.0.0.1/a.pdf',
    'http://169.254.169.254/latest', 'http://[::1]/a.pdf', 'https://user:pass@example.org/a.pdf',
    'https://example.org:8443/a.pdf', 'http://[::ffff:127.0.0.1]/a.pdf'])
def test_private_or_credential_urls_rejected(url):
    with pytest.raises(ImportFailure):
        public_url(url)


def test_filename_and_google_exports():
    assert filename('../../report.pdf') == 'report.pdf'
    with pytest.raises(ImportFailure):
        filename('macro.xlsm')
    assert direct_link('https://docs.google.com/document/d/example/edit') == 'https://docs.google.com/document/d/example/export?format=docx'
    assert direct_link('https://drive.google.com/file/d/example/view') == 'https://drive.google.com/uc?export=download&id=example'


def test_dns_is_checked_at_connection_and_numeric_address_is_pinned(monkeypatch):
    import socket
    answers = ['93.184.216.34']
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', (ip, 443)) for ip in answers])
    connections = []
    monkeypatch.setattr(httpcore.SyncBackend, 'connect_tcp', lambda self, host, port, **kw: connections.append(host))
    PublicBackend().connect_tcp('example.org', 443)
    assert connections == ['93.184.216.34']
    answers.append('10.0.0.1')
    with pytest.raises(ImportFailure, match='внутренние'):
        PublicBackend().connect_tcp('example.org', 443)
    assert len(connections) == 1


class Response:
    def __init__(self, status=200, headers=None, body=b'%PDF-1.4 synthetic'):
        self.status, self.headers, self.body = status, headers or [], body

    def iter_stream(self):
        yield self.body


class Pool:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @contextmanager
    def stream(self, *args, **kwargs):
        yield self.response


def test_download_preserves_original_and_cleans_temporary_file(tmp_path):
    path = download('https://example.org/report.pdf', tmp_path, pool_factory=lambda: Pool(Response()))
    assert path.name == 'report.pdf'
    assert path.read_bytes() == b'%PDF-1.4 synthetic'
    assert not (tmp_path / '.download.part').exists()
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('response', [Response(302, [(b'location', b'http://127.0.0.1/secret')]),
    Response(headers=[(b'content-type', b'text/html')]), Response(headers=[(b'content-length', b'999999999')]),
    Response(body=b''), Response(403)])
def test_download_failure_leaves_no_document(tmp_path, response):
    with pytest.raises(ImportFailure):
        download('https://example.org/report.pdf', tmp_path, pool_factory=lambda: Pool(response))
    assert list(tmp_path.iterdir()) == []


class Repository:
    def __init__(self):
        self.jobs = {}
        self.available = True

    def online(self):
        return self.available

    def create(self, **values):
        identifier = str(values.get('job_id') or uuid4())
        self.jobs[identifier] = {'id': identifier, 'status': 'queued', 'filename': values.get('filename')}
        return identifier

    def get(self, identifier):
        return self.jobs[str(identifier)]


def test_upload_requires_consent_and_preserves_file_until_worker_runs(tmp_path):
    repo = Repository()
    with TestClient(create_app(service=SimpleNamespace(), import_repository=repo, import_directory=tmp_path)) as client:
        assert client.post('/api/imports/file', files={'file': ('test.pdf', b'%PDF-1.4')}).status_code == 400
        result = client.post('/api/imports/file', data={'public_data': 'true'}, files={'file': ('test.pdf', b'%PDF-1.4')})
        assert result.status_code == 202
        job = result.json()
        assert (tmp_path / job['id'] / 'original' / 'test.pdf').read_bytes() == b'%PDF-1.4'
        assert client.get('/api/imports/' + job['id']).json()['status'] == 'queued'
        assert client.get('/api/imports/' + str(uuid4())).status_code == 404
        assert client.post('/api/imports/file', data={'public_data': 'true'}, files={'file': ('empty.pdf', b'')}).status_code == 400
        assert len(list(tmp_path.iterdir())) == 1
        repo.available = False
        assert client.post('/api/imports/url', json={'url': 'https://example.org/file.pdf', 'public_data': True}).status_code == 503


def test_link_import_rejects_private_address_and_missing_consent(tmp_path):
    repo = Repository()
    with TestClient(create_app(service=SimpleNamespace(), import_repository=repo, import_directory=tmp_path)) as client:
        assert client.post('/api/imports/url', json={'url': 'https://example.org/file.pdf'}).status_code == 422
        assert client.post('/api/imports/url', json={'url': 'http://127.0.0.1/file.pdf', 'public_data': True}).status_code == 400
        assert not repo.jobs
        assert client.post('/api/imports/url', json={'url': 'https://example.org/file.pdf', 'public_data': True}).status_code == 202


def test_request_body_is_limited_before_parsing(tmp_path, monkeypatch):
    import navigator.imports.routes as routes
    monkeypatch.setattr(routes, 'MAX_BYTES', 10)
    with TestClient(create_app(service=SimpleNamespace(), import_repository=Repository(), import_directory=tmp_path)) as client:
        response = client.post('/api/imports/file', content=b'x' * (1024 * 1024 + 11))
        assert response.status_code == 413
        assert list(tmp_path.iterdir()) == []
