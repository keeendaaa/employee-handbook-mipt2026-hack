"""Synthetic requests and mock mail transport; no real email or regulation data."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from navigator.workspace import install_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('MATERIAL_REQUEST_DB', str(tmp_path/'requests.sqlite'))
    monkeypatch.setenv('ADMIN_API_TOKEN', 'synthetic-test-admin')
    monkeypatch.setenv('MAILBOT_PANEL_URL', 'http://mailbot-admin:8787')
    app = FastAPI()
    install_routes(app)
    with TestClient(app) as client:
        yield client


AUTH = {'Authorization': 'Bearer synthetic-test-admin'}


def test_material_request_requires_consent_and_is_shared_only_with_admin(client):
    body = {'question': 'Синтетический вопрос', 'message': 'Нужен материал',
            'step': 'Синтетический шаг', 'source_ids': ['test-source']}
    assert client.post('/api/material-requests', json=body).status_code == 422
    created = client.post('/api/material-requests', json={**body,'public_data': True})
    assert created.status_code == 201
    assert client.get('/api/material-requests').status_code == 401
    rows = client.get('/api/material-requests', headers=AUTH).json()['requests']
    assert rows[0]['id'] == created.json()['id']
    assert rows[0]['source_ids'] == ['test-source']
    assert rows[0]['status'] == 'new'
    url = '/api/material-requests/'+rows[0]['id']
    assert client.patch(url, json={'status': 'closed'}).status_code == 401
    assert client.patch(url, json={'status': 'closed'}, headers=AUTH).status_code == 200
    assert client.get('/api/material-requests', headers=AUTH).json()['requests'][0]['status'] == 'closed'
    assert client.patch(url, json={'status': 'invented'}, headers=AUTH).status_code == 422
    assert client.post('/api/material-requests', json={**body,'message':'  ','public_data':True}).status_code == 422


def test_unconfigured_admin_is_unavailable_not_public(client, monkeypatch):
    monkeypatch.delenv('ADMIN_API_TOKEN')
    assert client.get('/api/material-requests', headers=AUTH).status_code == 503
    assert client.get('/api/admin/mail/status', headers=AUTH).status_code == 503


def test_mail_gateway_preserves_host_origin_and_propagates_success(client, monkeypatch):
    original = httpx.Client
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers['Host'] == '127.0.0.1:8787'
        assert request.headers['Origin'] == 'http://127.0.0.1:8787'
        assert 'authorization' not in request.headers
        return httpx.Response(200, json={'enabled': False} if request.method == 'POST' else {'worker':{'state':'paused'}})
    monkeypatch.setattr('navigator.workspace.httpx.Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    assert client.get('/api/admin/mail/status').status_code == 401
    assert requests == []
    assert client.get('/api/admin/mail/status', headers=AUTH).json()['worker']['state'] == 'paused'
    settings = {'enabled':False,'reply_without_issue':True,'senders':[],'api_url':''}
    assert client.post('/api/admin/mail/settings', json=settings, headers=AUTH).json()['enabled'] is False
    assert len(requests) == 2


def test_mail_gateway_never_follows_redirect_or_claims_success(client, monkeypatch):
    original = httpx.Client
    monkeypatch.setattr('navigator.workspace.httpx.Client', lambda **kw: original(**kw, transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'Location':'http://elsewhere.invalid'}))))
    assert client.get('/api/admin/mail/status', headers=AUTH).status_code == 502
    monkeypatch.delenv('MAILBOT_PANEL_URL')
    assert client.get('/api/admin/mail/status', headers=AUTH).status_code == 503
