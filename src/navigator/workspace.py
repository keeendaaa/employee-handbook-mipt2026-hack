"""Material requests and an authenticated, same-origin bridge to the mail panel.

The public demo has no employee identity. Requests contain explicitly shared public
text only. Progress remains on the employee's device; no HR completion is inferred.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MaterialRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)
    message: str = Field(min_length=1, max_length=3000)
    step: str = Field(default='', max_length=4000)
    source_ids: list[str] = Field(default_factory=list, max_length=25)
    public_data: Literal[True]

    @field_validator('source_ids')
    @classmethod
    def bounded_sources(cls, values):
        if any(len(value) > 200 for value in values):
            raise ValueError('Некорректная ссылка на источник')
        return list(dict.fromkeys(values))


class RequestState(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['new', 'review', 'closed']


class MailSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool
    reply_without_issue: bool
    senders: list[str] = Field(max_length=100)
    api_url: str = Field(max_length=2048)


class MaterialRepository:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('''CREATE TABLE IF NOT EXISTS material_requests
            (id TEXT PRIMARY KEY, question TEXT NOT NULL, message TEXT NOT NULL,
             step TEXT NOT NULL, source_ids TEXT NOT NULL, status TEXT NOT NULL,
             created_at TEXT NOT NULL)''')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add(self, body):
        import json
        record = {**body.model_dump(exclude={'public_data'}), 'id': str(uuid4()),
                  'status': 'new', 'created_at': datetime.now(timezone.utc).isoformat()}
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT count(*) FROM material_requests').fetchone()[0] >= 500:
                raise HTTPException(429, 'Достигнут лимит запросов материалов. Сообщите администратору.')
            conn.execute('INSERT INTO material_requests VALUES(?,?,?,?,?,?,?)',
                         (record['id'], record['question'], record['message'], record['step'],
                          json.dumps(record['source_ids']), record['status'], record['created_at']))
        return record

    def list(self):
        import json
        with self.connect() as conn:
            rows = conn.execute('SELECT * FROM material_requests ORDER BY created_at DESC LIMIT 500').fetchall()
        return [{**dict(row), 'source_ids': json.loads(row['source_ids'])} for row in rows]

    def update(self, request_id, status):
        with self.connect() as conn:
            cursor = conn.execute('UPDATE material_requests SET status=? WHERE id=?', (status, request_id))
            if not cursor.rowcount:
                raise HTTPException(404, 'Запрос материалов не найден.')
        return {'id': request_id, 'status': status}


def install_routes(app, admin):
    repository = MaterialRepository(os.environ.get('MATERIAL_REQUEST_DB', 'data/workspace/requests.sqlite'))

    @app.post('/api/material-requests', status_code=201)
    def create(body: MaterialRequest):
        return repository.add(body)

    @app.get('/api/material-requests')
    def requests(request: Request):
        admin(request)
        return {'requests': repository.list()}

    @app.patch('/api/material-requests/{request_id}')
    def update(request_id: str, body: RequestState, request: Request):
        admin(request)
        return repository.update(request_id, body.status)

    def mail_request(request, method, path, body=None):
        admin(request)
        base = os.environ.get('MAILBOT_PANEL_URL', '').rstrip('/')
        if not base:
            raise HTTPException(503, 'Почтовый бот не подключён. Настройте MAILBOT_PANEL_URL на сервере.')
        # Target is server configuration, never a value from the browser. Preserve
        # the mail panel's Host/Origin guards and never follow upstream redirects.
        try:
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.request(method, base + path, json=body,
                    headers={'Host': '127.0.0.1:8787', 'Origin': 'http://127.0.0.1:8787'})
            if response.status_code != 200:
                if response.status_code == 400:
                    raise HTTPException(400, 'Бот отклонил настройки. Проверьте адреса и URL обработчика.')
                raise HTTPException(502, 'Почтовая панель вернула ошибку. Повторите позже.')
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Не удалось подключиться к почтовой панели.') from None

    @app.get('/api/admin/mail/status')
    def mail_status(request: Request):
        return mail_request(request, 'GET', '/api/status')

    @app.post('/api/admin/mail/settings')
    def mail_settings(body: MailSettings, request: Request):
        return mail_request(request, 'POST', '/api/settings', body.model_dump())
