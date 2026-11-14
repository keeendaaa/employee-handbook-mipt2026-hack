"""Synthetic requests and mock mail transport; no real email or regulation data."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from navigator.workspace import install_routes
from navigator.admin_auth import AdminAuth, password_hash


@pytest.fixture
def client(tmp_path, monkeypatch, admin_credentials):
    monkeypatch.setenv('MATERIAL_REQUEST_DB', str(tmp_path/'requests.sqlite'))
    monkeypatch.setenv('MAILBOT_PANEL_URL', 'http://mailbot-admin:8787')
    app = FastAPI()
    auth = AdminAuth(str(tmp_path / 'requests.sqlite'))
    auth.install(app)
    install_routes(app, auth.require)
    with TestClient(app, base_url='https://testserver') as client:
        yield client


def sign_in(client, credentials):
    response = client.post('/api/admin/session', json=credentials)
    assert response.status_code == 200
    assert all(flag in response.headers['set-cookie'] for flag in ('HttpOnly', 'Secure', 'SameSite=strict'))



def test_material_request_requires_consent_and_is_shared_only_with_admin(client, admin_credentials):
    body = {'question': 'Синтетический вопрос', 'message': 'Нужен материал',
            'step': 'Синтетический шаг', 'source_ids': ['test-source']}
    assert client.post('/api/material-requests', json=body).status_code == 422
    created = client.post('/api/material-requests', json={**body,'public_data': True})
    assert created.status_code == 201
    assert client.get('/api/material-requests').status_code == 401
    assert client.patch('/api/material-requests/' + created.json()['id'], json={'status': 'closed'}).status_code == 401
    sign_in(client, admin_credentials)
    rows = client.get('/api/material-requests').json()['requests']
    assert rows[0]['id'] == created.json()['id']
    assert rows[0]['source_ids'] == ['test-source']
    assert rows[0]['status'] == 'new'
    url = '/api/material-requests/'+rows[0]['id']
    assert client.patch(url, json={'status': 'closed'}).status_code == 200
    assert client.get('/api/material-requests').json()['requests'][0]['status'] == 'closed'
    assert client.patch(url, json={'status': 'invented'}).status_code == 422
    assert client.post('/api/material-requests', json={**body,'message':'  ','public_data':True}).status_code == 422


def test_session_validates_password_origin_and_logout(client, admin_credentials):
    assert client.post('/api/admin/session', json={**admin_credentials, 'password': 'wrong'}).status_code == 401
    assert client.post('/api/admin/session', json=admin_credentials,
                       headers={'Origin': 'https://other.invalid'}).status_code == 403
    sign_in(client, admin_credentials)
    cookie = client.cookies.get('smena_admin')
    assert client.get('/api/admin/session').json() == {'username': 'synthetic-admin'}
    assert client.delete('/api/admin/session').status_code == 200
    assert client.get('/api/admin/session', headers={'Cookie': f'smena_admin={cookie}'}).status_code == 401


def test_demo_credentials_are_local_only(client, tmp_path, monkeypatch, admin_credentials):
    path = tmp_path / 'demo.hash'
    path.write_text(password_hash('synthetic-local-password'))
    monkeypatch.setenv('ADMIN_TEST_USERNAME', 'synthetic-demo')
    monkeypatch.setenv('ADMIN_TEST_PASSWORD_HASH_FILE', str(path))
    credentials = {'username': 'synthetic-demo', 'password': 'synthetic-local-password'}
    assert client.post('/api/admin/session', json=credentials).status_code == 401
    with TestClient(client.app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 1000)) as local:
        assert local.post('/api/admin/session', json=credentials,
                          headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 403
        assert local.post('/api/admin/session', json=credentials).status_code == 200
        assert local.get('/api/admin/session').status_code == 200
        cookie = local.cookies.get('smena_admin')
    assert client.get('/api/admin/session', headers={'Cookie': f'smena_admin={cookie}'}).status_code == 401


def test_mail_gateway_preserves_host_origin_and_propagates_success(client, monkeypatch, admin_credentials):
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
    sign_in(client, admin_credentials)
    assert client.get('/api/admin/mail/status').json()['worker']['state'] == 'paused'
    settings = {'enabled':False,'reply_without_issue':True,'senders':[],'api_url':''}
    assert client.post('/api/admin/mail/settings', json=settings).json()['enabled'] is False
    assert len(requests) == 2


def test_mail_gateway_never_follows_redirect_or_claims_success(client, monkeypatch, admin_credentials):
    sign_in(client, admin_credentials)
    original = httpx.Client
    monkeypatch.setattr('navigator.workspace.httpx.Client', lambda **kw: original(**kw, transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'Location':'http://elsewhere.invalid'}))))
    assert client.get('/api/admin/mail/status').status_code == 502
    monkeypatch.delenv('MAILBOT_PANEL_URL')
    assert client.get('/api/admin/mail/status').status_code == 503
