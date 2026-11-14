import pytest

from navigator.admin_auth import password_hash


@pytest.fixture
def admin_credentials(tmp_path, monkeypatch):
    config = tmp_path / 'auth'
    config.mkdir()
    path = config / 'admin.hash'
    path.write_text(password_hash('synthetic-test-password'))
    monkeypatch.setenv('ADMIN_USERNAME', 'synthetic-admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH_FILE', str(path))
    monkeypatch.setenv('MATERIAL_REQUEST_DB', str(config / 'requests.sqlite'))
    return {'username': 'synthetic-admin', 'password': 'synthetic-test-password'}
