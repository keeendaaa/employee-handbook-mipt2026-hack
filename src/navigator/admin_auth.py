"""Password authentication and revocable sessions for the administration API."""

from collections import defaultdict, deque
from hashlib import pbkdf2_hmac, sha256
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
import time

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field


COOKIE = "smena_admin"
SESSION_SECONDS = 8 * 3600
ITERATIONS = 600_000


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}:{derive(password, salt).hex()}"


def derive(password: str, salt: bytes) -> bytes:
    return pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)


def session_id(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def local_request(request: Request) -> bool:
    peers = {"127.0.0.1", "::1"}
    peers.update(peer.strip() for peer in os.environ.get("ADMIN_LOCAL_PEERS", "").split(",") if peer.strip())
    return (
        request.url.hostname in {"localhost", "127.0.0.1", "::1"}
        and request.client is not None
        and request.client.host in peers
        and not any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host"))
    )


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return  # Non-browser clients and same-origin clients that omit Origin.
    if origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Источник запроса не совпадает с адресом приложения.")


class AdminAuth:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.attempts = defaultdict(deque)
        self.global_attempts = deque()
        self.lock = Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS admin_sessions (
                token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
                expires INTEGER NOT NULL, local_only INTEGER NOT NULL
            )""")

    def require(self, request: Request) -> str:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_same_origin(request)
        token = request.cookies.get(COOKIE, "")
        if token and len(token) == 43 and (request.url.scheme == "https" or local_request(request)):
            with sqlite3.connect(self.db_path) as db:
                row = db.execute(
                    "SELECT username, local_only FROM admin_sessions WHERE token_hash=? AND expires>?",
                    (session_id(token), int(time.time())),
                ).fetchone()
            if row and (not row[1] or local_request(request)):
                return row[0]
        raise HTTPException(401, "Войдите как администратор.")

    def limit(self, request: Request) -> None:
        now = time.monotonic()
        peer = request.client.host if request.client else "unknown"
        with self.lock:
            for bucket in [self.global_attempts, *self.attempts.values()]:
                while bucket and bucket[0] <= now - 60:
                    bucket.popleft()
            self.attempts = defaultdict(deque, {key: bucket for key, bucket in self.attempts.items() if bucket})
            if len(self.global_attempts) >= 40 or len(self.attempts.get(peer, ())) >= 6:
                raise HTTPException(429, "Слишком много попыток входа. Повторите через минуту.")
            self.global_attempts.append(now)
            self.attempts[peer].append(now)

    def install(self, app):
        @app.post("/api/admin/session")
        def login(body: Credentials, request: Request, response: Response):
            require_same_origin(request)
            local = local_request(request)
            if request.url.scheme != "https" and not local:
                raise HTTPException(403, "Для входа откройте сайт через HTTPS.")
            self.limit(request)
            username = os.environ.get("ADMIN_USERNAME", "")
            local_only = local and body.username == os.environ.get("ADMIN_TEST_USERNAME", "")
            hash_file = os.environ.get("ADMIN_TEST_PASSWORD_HASH_FILE" if local_only else "ADMIN_PASSWORD_HASH_FILE")
            stored = Path(hash_file).read_text().strip() if hash_file and Path(hash_file).is_file() else ""
            try:
                salt, expected = map(bytes.fromhex, stored.split(":")) if stored else (bytes(16), bytes(32))
                if len(salt) != 16 or len(expected) != 32:
                    raise ValueError("Wrong hash length")
            except ValueError as error:
                raise HTTPException(503, "Вход администратора не настроен.") from error
            password_ok = hmac.compare_digest(derive(body.password, salt), expected)
            if not stored or not password_ok or (not local_only and body.username != username):
                raise HTTPException(401, "Неверный логин или пароль.")
            token = secrets.token_urlsafe(32)
            now = int(time.time())
            with sqlite3.connect(self.db_path) as db:
                db.execute("DELETE FROM admin_sessions WHERE expires<=?", (now,))
                previous = request.cookies.get(COOKIE)
                if previous:
                    db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (session_id(previous),))
                db.execute("INSERT INTO admin_sessions VALUES (?, ?, ?, ?)",
                           (session_id(token), body.username, now + SESSION_SECONDS, local_only))
            response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                                secure=request.url.scheme == "https", samesite="strict", path="/api")
            return {"username": body.username}

        @app.get("/api/admin/session")
        def session(request: Request):
            return {"username": self.require(request)}

        @app.delete("/api/admin/session")
        def logout(request: Request, response: Response):
            require_same_origin(request)
            token = request.cookies.get(COOKIE)
            if token:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (session_id(token),))
            response.delete_cookie(COOKIE, path="/api", httponly=True, samesite="strict",
                                   secure=request.url.scheme == "https")
            return {"username": None}
