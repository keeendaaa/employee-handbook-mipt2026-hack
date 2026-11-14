"""Single-process HTTP service: local retrieval and external grounded generation."""

from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
import os
from pathlib import Path
import threading
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import psycopg

from .admin_auth import AdminAuth
from .generation import Generator, GenerationError
from .ingest.storage import Store, IndexUnavailableError
from .retrieval import RetrievalService
from .sources import resolve


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=20000)
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Введите вопрос")
        return value.strip()


class MailQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    subject: str = Field(default="", max_length=512)
    body: str = Field(default="", max_length=20000)

    @model_validator(mode="after")
    def nonblank(self):
        if not (self.subject or self.body):
            raise ValueError("Укажи тему или текст письма")
        return self


class LiveQuery(Query):
    mode: Literal['ask', 'search'] = 'ask'


def create_app(*, service=None, generator=None, import_repository=None, import_directory=None,
               knowledge_map=None, map_questions=None, frontend_directory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        if service is not None:
            app.state.service, app.state.generator = service, generator
        else:
            from .ingest.embedding import LocalEmbedder
            import torch
            torch.set_num_threads(int(os.environ.get("EMBEDDING_THREADS", "2")))
            store = Store(os.environ["DATABASE_URL"])
            store.active_revision()
            embedder = LocalEmbedder(Path(os.environ.get("MODEL_DIR", "models/multilingual-e5-small")))
            app.state.service = RetrievalService(store, embedder)
            key_path = os.environ.get("LLM_API_KEY_FILE")
            key = Path(key_path).read_text().strip() if key_path else os.environ.get("LLM_API_KEY", "")
            app.state.generator = Generator(key, model=os.environ.get("LLM_MODEL", "Qwen/Qwen3.8-27B"),
                base_url=os.environ.get("LLM_BASE_URL", "https://api.commandcode.ai/provider/v1")) if key else None
        from .imports.repository import ImportRepository
        app.state.import_repository = import_repository if import_repository is not None else (ImportRepository(app.state.service.store) if service is None else None)
        app.state.import_directory = Path(import_directory or os.environ.get("IMPORT_DIR", "data/imports"))
        if app.state.import_repository is not None:
            app.state.import_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        from .knowledge.graph import KnowledgeMap
        from .knowledge.repository import QuestionRepository
        app.state.knowledge_map = knowledge_map
        if knowledge_map is None and hasattr(app.state.service, 'embedder'):
            app.state.knowledge_map = KnowledgeMap(app.state.service.store, app.state.service.embedder)
        app.state.map_questions = map_questions
        if map_questions is None and app.state.knowledge_map is not None:
            app.state.map_questions = QuestionRepository(app.state.service.store)
        yield
        if knowledge_map is None and app.state.knowledge_map is not None:
            app.state.knowledge_map.close()
        if service is None and app.state.generator:
            app.state.generator.close()

    app = FastAPI(title="Навигатор сотрудника", lifespan=lifespan)
    web_directory = Path(frontend_directory) if frontend_directory else Path(__file__).parent / 'web'
    search_lock, ask_lock = threading.Lock(), threading.Lock()
    rate_lock = threading.Lock()
    calls = defaultdict(deque)
    global_calls = deque()

    def retrieve(query, progress=None):
        if not search_lock.acquire(blocking=False):
            raise HTTPException(429, "Поиск занят. Повторите запрос через несколько секунд.")
        try:
            if progress is not None:
                return app.state.service.search(query.question, limit=query.limit, progress=progress)
            return app.state.service.search(query.question, limit=query.limit)
        finally:
            search_lock.release()

    @app.exception_handler(GenerationError)
    def generation_error(request, exc):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(IndexUnavailableError)
    def index_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Индекс недоступен. Сообщите администратору."})

    @app.exception_handler(psycopg.Error)
    def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": "База данных недоступна. Повторите запрос позже."})

    @app.exception_handler(ValueError)
    def value_error(request, exc):
        # Do not return arbitrary internal exception text, connection strings or file paths.
        return JSONResponse(status_code=400, content={"detail": "Не удалось обработать запрос. Проверьте вопрос и параметры."})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        frontend = web_directory / 'index.html'
        if frontend.is_file():
            return FileResponse(frontend)
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get('/legacy', include_in_schema=False)
    def legacy():
        return FileResponse(Path(__file__).parent / 'static' / 'index.html')

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        revision = app.state.service.store.active_revision()
        return {"status": "ready", "corpus_revision": revision["corpus_key"],
                "generation_configured": app.state.generator is not None}

    @app.post("/api/search")
    def search(query: Query):
        return retrieve(query)

    @contextmanager
    def generation_slot(request):
        if app.state.generator is None:
            raise HTTPException(503, "API модели не настроен. Доступен поиск без генерации.")
        if not ask_lock.acquire(blocking=False):
            raise HTTPException(429, "Модель обрабатывает другой вопрос. Повторите запрос позже.")
        try:
            now = time.monotonic()
            ip = request.client.host if request.client else "unknown"
            with rate_lock:
                # Limit public-demo API spend; do not trust forwarded headers.
                for old_ip in list(calls):
                    while calls[old_ip] and calls[old_ip][0] < now - 3600:
                        calls[old_ip].popleft()
                    if not calls[old_ip]:
                        del calls[old_ip]
                while global_calls and global_calls[0] < now - 3600:
                    global_calls.popleft()
                if len(calls[ip]) >= 15 or len(global_calls) >= 60:
                    raise HTTPException(429, "Лимит демонстрации исчерпан. Повторите позже или используйте поиск.")
                calls[ip].append(now)
                global_calls.append(now)
            yield app.state.generator
        finally:
            ask_lock.release()

    def answer_query(query: Query, request: Request, *, progress=None):
        with generation_slot(request) as generator:
            retrieved = retrieve(query, progress)
            if progress is not None:
                initial_trace = send_retrieval(progress, retrieved)
                result = generator.answer(query.question, retrieved, progress=progress)
                if initial_trace['map_status'] == 'building':
                    updated_trace = make_trace(retrieved)
                    if updated_trace['map_status'] == 'ready':
                        progress({'type': 'map_update', 'trace': updated_trace})
                progress({'type': 'answer', 'answer': result})
                return result
            return generator.answer(query.question, retrieved)

    @app.post("/api/ask")
    def ask(query: Query, request: Request):
        return answer_query(query, request)

    @app.post("/api/mail/analyze")
    def analyze_mail(mail: MailQuery, request: Request):
        with generation_slot(request) as generator:
            intent = generator.classify_mail(mail.subject, mail.body)
            if intent.question is None:
                return {"result_type": "no_action"}
            query = Query(question=intent.question)
            return generator.answer(query.question, retrieve(query))

    def make_trace(retrieved, *, include_context=True):
        from .live import retrieval_trace
        try:
            trace = retrieval_trace(retrieved, app.state.knowledge_map, include_context=include_context)
        except Exception:
            # Optional visual grouping must not invalidate a valid RAG result.
            trace = retrieval_trace(retrieved, None, include_context=include_context)
        return trace

    def send_retrieval(progress, retrieved, *, include_context=True):
        trace = make_trace(retrieved, include_context=include_context)
        progress({'type': 'retrieval', 'retrieval': retrieved, 'trace': trace})
        return trace

    @app.post('/api/query/stream')
    def live_query(query: LiveQuery, request: Request):
        from .live import stream_response
        if query.mode == 'ask' and app.state.generator is None:
            raise HTTPException(503, 'API модели не настроено. Используйте «Только поиск».')
        def run(progress):
            progress({'type': 'started', 'mode': query.mode})
            if query.mode == 'ask':
                answer_query(query, request, progress=progress)
            else:
                retrieved = retrieve(query, progress)
                send_retrieval(progress, retrieved, include_context=False)
                progress({'type': 'search_complete', 'retrieval': retrieved})
        return stream_response(run)

    @app.get("/api/documents/{document_id}")
    def document(document_id: str, corpus_revision: str):
        store = app.state.service.store
        active = store.active_revision()
        if active is None:
            raise HTTPException(503, "База документов не подключена.")
        if active["corpus_key"] != corpus_revision:
            raise HTTPException(409, "База обновилась. Обновите список регламентов.")
        doc = store.document_in_corpus(document_id, corpus_revision)
        if doc is None:
            raise HTTPException(404, "Документ отсутствует в этой версии базы.")
        return {"id": doc["document_id"], "name": doc["name"],
                "version_id": doc["version_id"], "corpus_revision": corpus_revision,
                "warnings": doc["warnings"], "blocks": [
                    {"text": b["text"], "locator": b["locator"], "method": b.get("method", "native")}
                    for b in doc["blocks"]]}

    @app.get("/api/sources/{source_id}")
    def source(source_id: str):
        try:
            return resolve(app.state.service.store, source_id)
        except (ValueError, KeyError):
            raise HTTPException(404, "Фрагмент не найден или ссылка некорректна.") from None

    from .workspace import install_routes as install_workspace_routes
    from .imports.routes import install_routes
    from .knowledge.routes import install_routes as install_map_routes
    auth = AdminAuth(os.environ.get('MATERIAL_REQUEST_DB', 'data/workspace/requests.sqlite'))
    auth.install(app)
    install_workspace_routes(app, auth.require)
    install_routes(app, auth.require)
    install_map_routes(app, answer=lambda question, request: ask(Query(question=question), request),
                       admin=auth.require)
    frontend_assets = web_directory / 'ui-assets'
    if frontend_assets.is_dir():
        app.mount('/ui-assets', StaticFiles(directory=frontend_assets), name='ui-assets')
    frontend_images = web_directory / 'illustrations'
    if frontend_images.is_dir():
        app.mount('/illustrations', StaticFiles(directory=frontend_images), name='illustrations')
    frontend_brand = web_directory / 'brand'
    if frontend_brand.is_dir():
        app.mount('/brand', StaticFiles(directory=frontend_brand), name='brand')
    app.mount('/assets', StaticFiles(directory=Path(__file__).parent / 'static'), name='assets')
    return app


app = create_app()
