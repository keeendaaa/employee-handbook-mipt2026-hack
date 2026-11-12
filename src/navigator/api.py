"""Single-process HTTP service: local retrieval and external grounded generation."""

from collections import defaultdict, deque
from contextlib import asynccontextmanager
import os
from pathlib import Path
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psycopg

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


def create_app(*, service=None, generator=None) -> FastAPI:
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
        yield
        if service is None and app.state.generator:
            app.state.generator.close()

    app = FastAPI(title="Навигатор сотрудника", lifespan=lifespan)
    search_lock, ask_lock = threading.Lock(), threading.Lock()
    rate_lock = threading.Lock()
    calls = defaultdict(deque)
    global_calls = deque()

    def retrieve(query):
        if not search_lock.acquire(blocking=False):
            raise HTTPException(429, "Поиск занят. Повторите запрос через несколько секунд.")
        try:
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
        return FileResponse(Path(__file__).parent / "static" / "index.html")

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

    @app.post("/api/ask")
    def ask(query: Query, request: Request):
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
            retrieved = retrieve(query)
            return app.state.generator.answer(query.question, retrieved)
        finally:
            ask_lock.release()

    @app.get("/api/sources/{source_id}")
    def source(source_id: str):
        try:
            return resolve(app.state.service.store, source_id)
        except (ValueError, KeyError):
            raise HTTPException(404, "Фрагмент не найден или ссылка некорректна.") from None

    return app


app = create_app()
