"""Upload and public-link endpoints. Originals and signed URLs never enter logs."""

from collections import defaultdict, deque
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Literal
from uuid import UUID, uuid4

from fastapi import File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from .download import ImportFailure, MAX_BYTES, direct_link, filename


class ImportBodyLimit:
    """Bound request bodies before a multipart parser can spool unbounded data."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST' or not scope.get('path', '').startswith('/api/imports'):
            return await self.app(scope, receive, send)
        maximum = MAX_BYTES + 1024 * 1024 if scope['path'].endswith('/file') else 8192
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                size += len(chunk)
                if size > maximum:
                    return await JSONResponse({'detail': 'Превышен лимит загрузки: файл до 25 МБ.'}, status_code=413)(scope, receive, send)
                body.write(chunk)
                if not message.get('more_body', False):
                    break
            body.seek(0)
            remaining = size
            delivered = False
            async def replay():
                nonlocal remaining, delivered
                if remaining or not delivered:
                    delivered = True
                    chunk = body.read(min(65536, remaining))
                    remaining -= len(chunk)
                    return {'type': 'http.request', 'body': chunk, 'more_body': remaining > 0}
                return await receive()
            return await self.app(scope, replay, send)



class LinkImport(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    url: str = Field(min_length=1, max_length=4096)
    public_data: Literal[True]
    replace_existing: bool = False


def install_routes(app):
    calls, lock = defaultdict(deque), threading.Lock()

    def repository(request):
        value = request.app.state.import_repository
        if value is None or not value.online():
            raise HTTPException(503, 'Обработчик документов недоступен. Повторите позже.')
        ip = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        with lock:
            for key in list(calls):
                while calls[key] and calls[key][0] < now - 3600:
                    calls[key].popleft()
                if not calls[key]:
                    del calls[key]
            if len(calls[ip]) >= 10:
                raise HTTPException(429, 'Лимит загрузок с этого адреса исчерпан: 10 в час.')
            calls[ip].append(now)
        return value

    @app.exception_handler(ImportFailure)
    def import_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.post('/api/imports/file', status_code=202)
    def upload(request: Request, file: UploadFile = File(...), public_data: bool = Form(False),
               replace_existing: bool = Form(False)):
        if not public_data:
            raise HTTPException(400, 'Подтвердите, что файл неконфиденциальный и разрешён для общей базы и внешнего API.')
        name = filename(file.filename or '')
        repo = repository(request)
        job_id = uuid4()
        folder = request.app.state.import_directory / str(job_id)
        original = folder / 'original'
        original.mkdir(parents=True, mode=0o700)
        created = False
        try:
            size = 0
            fd = os.open(original / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as output:
                while chunk := file.file.read(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, 'Файл превышает лимит 25 МБ.')
                    output.write(chunk)
            if not size:
                raise HTTPException(400, 'Пустой файл не принимается.')
            repo.create(job_id=job_id, filename=name, replace_existing=replace_existing)
            created = True
            return repo.get(job_id)
        finally:
            file.file.close()
            if not created:
                shutil.rmtree(folder, ignore_errors=False)

    @app.post('/api/imports/url', status_code=202)
    def link(body: LinkImport, request: Request):
        url = direct_link(body.url)
        repo = repository(request)
        job_id = repo.create(source_url=url, replace_existing=body.replace_existing)
        return repo.get(job_id)

    @app.get('/api/imports/{job_id}')
    def status(job_id: UUID, request: Request):
        repo = request.app.state.import_repository
        if repo is None:
            raise HTTPException(503, 'Импорт не настроен.')
        try:
            return repo.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Задача импорта не найдена.') from None

    app.add_middleware(ImportBodyLimit)
