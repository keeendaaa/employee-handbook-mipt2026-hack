import imaplib
import json
import logging
import os
import re
import smtplib
import sqlite3
import ssl
import sys
import time
from contextlib import contextmanager
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .navigator_client import DEFAULT_URL, NavigatorError, NoRedirect, ask

MAILBOX = os.environ.get("MAILBOT_ADDRESS", "").strip().lower()
DATABASE = Path(os.environ.get("MAILBOT_DB", "/data/mailbot.sqlite"))
PASSWORD = Path("/run/secrets/mail_password")
RESEND_KEY = Path("/run/secrets/resend_api_key")
PANEL = Path(__file__).with_name("panel.html")
POLL = 15
ADDRESS = re.compile(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+")
MESSAGE_ID = re.compile(r"<[^<>\s]+@[^<>\s]+>")
DEFAULTS = {"enabled": True, "senders": [], "api_url": os.environ.get("MAILBOT_API_URL", DEFAULT_URL)}
STUB_REPLY = "Письмо получено. Разбор пока работает в тестовом режиме."
MAX_MESSAGE = 2_000_000


@contextmanager
def database():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    with database() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, generation INTEGER NOT NULL, uid INTEGER NOT NULL,
                sender TEXT NOT NULL, subject TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '', updated INTEGER NOT NULL,
                UNIQUE(generation, uid)
            );
        """)


def get(conn, key, default=None):
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def put(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(value)))


def report(state, detail=""):
    with database() as conn:
        put(conn, "worker", {"state": state, "detail": detail, "updated": int(time.time())})


def valid_settings(raw):
    if not isinstance(raw, dict) or set(raw) != set(DEFAULTS):
        raise ValueError("Проверь поля настроек.")
    if type(raw["enabled"]) is not bool or not isinstance(raw["senders"], list):
        raise ValueError("Проверь состояние бота и список отправителей.")
    if len(raw["senders"]) > 100 or any(
        not isinstance(address, str) or len(address) > 254 or not ADDRESS.fullmatch(address)
        for address in raw["senders"]
    ):
        raise ValueError("Укажи до 100 полных почтовых адресов, по одному в строке.")
    url = raw["api_url"]
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        raise ValueError("Проверь адрес API.")
    if url:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.fragment or parsed.query or not parsed.path.endswith("/api/ask")):
            raise ValueError("Укажи HTTPS-адрес /api/ask без параметров и учётных данных.")
        parsed.port  # Reject invalid port numbers before saving the settings.
    return {
        "enabled": raw["enabled"],
        "senders": sorted({address.casefold() for address in raw["senders"]}),
        "api_url": url,
    }


def imap_ok(result):
    status, data = result
    if status != "OK":
        raise imaplib.IMAP4.error("Команда IMAP отклонена.")
    return data


def read_message(inbox, uid):
    size_data = imap_ok(inbox.uid("FETCH", str(uid), "(RFC822.SIZE)"))
    if not size_data or size_data[0] is None:
        return None, "Письмо удалено"
    size = re.search(rb"RFC822.SIZE (\d+)", size_data[0])
    if not size or int(size[1]) > MAX_MESSAGE:
        return None, "Письмо больше 2 МБ или размер неизвестен"
    parts = imap_ok(inbox.uid("FETCH", str(uid), "(BODY.PEEK[])"))
    for part in parts:
        if isinstance(part, tuple):
            return BytesParser(policy=policy.default).parsebytes(part[1]), ""
    return None, "Письмо удалено"


def inspect(message, settings):
    if message is None:
        return "", "", ""
    subject = str(message.get("Subject", ""))[:512]
    header = message.get("From")
    addresses = header.addresses if header else ()
    sender = addresses[0].addr_spec.casefold() if len(addresses) == 1 else ""
    if not ADDRESS.fullmatch(sender) or sender == MAILBOX or sender.split("@")[0] in {"mailer-daemon", "postmaster"}:
        return sender, subject, "Служебный или недействительный отправитель"
    auto = str(message.get("Auto-Submitted", "no")).split(";")[0].strip().lower()
    precedence = str(message.get("Precedence", "")).strip().lower()
    if (auto != "no" or precedence in {"bulk", "list", "junk"} or message.get("List-Id")
            or str(message.get("Return-Path", "")).strip() == "<>"
            or message.get_content_type() == "multipart/report"):
        return sender, subject, "Автоматическое письмо или рассылка"
    if settings["senders"] and sender not in settings["senders"]:
        return sender, subject, "Отправитель вне списка"
    return sender, subject, ""


def update(conn, generation, uid, status, detail="", attempts=0, retry_at=0):
    conn.execute("""
        UPDATE messages SET status=?, detail=?, attempts=?, retry_at=?, updated=?
        WHERE generation=? AND uid=?
    """, (status, detail, attempts, retry_at, int(time.time()), generation, uid))


def send_with_resend(reply, body, generation, uid, attempts):
    key = RESEND_KEY.read_text().strip()
    if not key:
        raise ValueError("Пустой ключ Resend")
    payload = {
        "from": MAILBOX,
        "to": [str(reply["To"])],
        "subject": str(reply["Subject"]),
        "text": body,
        "headers": {
            name: str(reply[name])
            for name in ("Auto-Submitted", "In-Reply-To", "References")
            if reply[name]
        },
    }
    request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"mailbot/{MAILBOX}/{generation}/{uid}",
        },
    )
    with database() as conn:
        update(conn, generation, uid, "sending", attempts=attempts)
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        result = json.loads(response.read(8192))
    if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
        raise ValueError("Resend не вернул идентификатор письма")


def deliver(password, tls, original, sender, subject, body, generation, uid, attempts):
    reply = EmailMessage()
    reply["From"] = MAILBOX
    reply["To"] = sender
    reply["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    reply["Date"] = formatdate(usegmt=True)
    reply["Message-ID"] = make_msgid(domain=MAILBOX.split("@")[1])
    reply["Auto-Submitted"] = "auto-replied"
    original_id = str(original.get("Message-ID", ""))
    if MESSAGE_ID.fullmatch(original_id):
        reply["In-Reply-To"] = original_id
        references = MESSAGE_ID.findall(str(original.get("References", "")))[-15:]
        reply["References"] = " ".join([*references, original_id])
    reply.set_content(body)
    if RESEND_KEY.exists():
        send_with_resend(reply, body, generation, uid, attempts)
        with database() as conn:
            update(conn, generation, uid, "sent", attempts=attempts)
        return

    with smtplib.SMTP("smtp.timeweb.ru", 587, timeout=15) as smtp:
        smtp.starttls(context=tls)
        smtp.login(MAILBOX, password)
        with database() as conn:
            update(conn, generation, uid, "sending", attempts=attempts)
        smtp.send_message(reply, from_addr=MAILBOX, to_addrs=[sender])
        with database() as conn:
            update(conn, generation, uid, "sent", attempts=attempts)


def process(inbox, generation, uid, settings, password, tls):
    message, reason = read_message(inbox, uid)
    sender, subject, filter_reason = inspect(message, settings)
    reason = reason or filter_reason
    with database() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO messages (generation, uid, sender, subject, status, updated)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (generation, uid, sender, subject, int(time.time())))
        row = conn.execute("SELECT status, attempts, retry_at FROM messages WHERE generation=? AND uid=?",
                           (generation, uid)).fetchone()
        if row["status"] not in {"pending", "retry"} or row["retry_at"] > time.time():
            return
        if reason:
            update(conn, generation, uid, "skipped", reason, row["attempts"])
            return
    attempts = row["attempts"] + 1
    stage = "API разбора"
    try:
        part = message.get_body(preferencelist=("plain",))
        body = part.get_content() if part else ""
        api_url = settings["api_url"]
        reply = ask(api_url, body) if api_url else STUB_REPLY
        stage = "Resend" if RESEND_KEY.exists() else "SMTP"
        deliver(password, tls, message, sender, subject, reply, generation, uid, attempts)
    except NavigatorError as error:
        with database() as conn:
            if error.retry_after is None or attempts >= 5:
                update(conn, generation, uid, "failed", f"Навигатор · {error}", attempts)
            else:
                delay = max(error.retry_after, 30 * 2 ** (attempts - 1))
                update(conn, generation, uid, "retry", f"Навигатор · {error}",
                       attempts, time.time() + delay)
    except (OSError, smtplib.SMTPException, ValueError, TypeError, LookupError) as error:
        with database() as conn:
            status = conn.execute("SELECT status FROM messages WHERE generation=? AND uid=?",
                                  (generation, uid)).fetchone()["status"]
            if status == "sent":
                return
            detail = f"{stage} · {type(error).__name__}"
            resend_status = error.code if stage == "Resend" and isinstance(error, HTTPError) else None
            if resend_status is not None:
                detail = f"Resend · HTTP {resend_status}"
            rejected = isinstance(error, smtplib.SMTPResponseException) or (
                resend_status is not None and 400 <= resend_status < 500 and resend_status != 409
            )
            if status == "sending" and not rejected:
                update(conn, generation, uid, "uncertain", detail, attempts)
            elif (isinstance(error, smtplib.SMTPResponseException) and error.smtp_code >= 500
                  or resend_status is not None and resend_status != 429
                  or attempts >= 5 and resend_status != 429
                  and not (stage == "SMTP" and isinstance(error, TimeoutError))):
                update(conn, generation, uid, "failed", detail, attempts)
            else:
                delay = min(900, 30 * 2 ** min(attempts - 1, 5))
                update(conn, generation, uid, "retry", detail, attempts, time.time() + delay)


def poll(settings, password, tls):
    with imaplib.IMAP4("imap.timeweb.ru", 143, timeout=15) as inbox:
        inbox.starttls(ssl_context=tls)
        inbox.login(MAILBOX, password)
        imap_ok(inbox.select("INBOX", readonly=True))
        generation = int(inbox.response("UIDVALIDITY")[1][0])
        next_uid = int(inbox.response("UIDNEXT")[1][0])
        with database() as conn:
            cursor = get(conn, "cursor")
            if cursor is None or cursor[0] != generation:
                conn.execute("""
                    UPDATE messages SET status='failed', detail='Изменился UIDVALIDITY ящика'
                    WHERE generation != ? AND status IN ('retry', 'pending')
                """, (generation,))
                cursor = [generation, next_uid - 1]
                put(conn, "cursor", cursor)
            retries = conn.execute("""
                SELECT uid FROM messages WHERE generation=? AND status IN ('retry', 'pending')
                AND retry_at <= ? AND uid <= ? ORDER BY uid LIMIT 20
            """, (generation, time.time(), cursor[1])).fetchall()

        report("online")
        for row in retries:
            process(inbox, generation, row["uid"], settings, password, tls)
        start = cursor[1] + 1
        if next_uid <= start:
            return
        data = imap_ok(inbox.uid("SEARCH", None, "UID", f"{start}:{next_uid - 1}"))
        for uid in sorted(int(item) for item in (data[0] or b"").split())[:25]:
            process(inbox, generation, uid, settings, password, tls)
            with database() as conn:
                put(conn, "cursor", [generation, uid])


def worker():
    tls = ssl.create_default_context()
    with database() as conn:
        conn.execute("""
            UPDATE messages SET status='uncertain', detail='Перезапуск во время отправки'
            WHERE status='sending'
        """)
    while True:
        with database() as conn:
            settings = get(conn, "settings", DEFAULTS)
        if settings["enabled"]:
            try:
                password = PASSWORD.read_text().rstrip("\r\n")
                if not password:
                    raise ValueError("Пустой секрет")
                poll(settings, password, tls)
            except imaplib.IMAP4.error:
                report("error", "IMAP отклонил команду. Проверь пароль и доступ к ящику.")
                logging.warning("IMAP command rejected")
            except (OSError, ValueError, TypeError) as error:
                report("error", f"Проверь подключение к ящику и файл секрета ({type(error).__name__}).")
                logging.warning("Mailbox check failed: %s", type(error).__name__)
        else:
            report("paused")
        time.sleep(POLL)


class Admin(BaseHTTPRequestHandler):
    def allowed(self):
        # Compose binds the panel to loopback. Check Host to prevent DNS rebinding.
        return self.headers.get("Host") == "127.0.0.1:8787"

    def respond(self, code, body, mime="application/json"):
        if mime == "application/json":
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed():
            return self.respond(403, {"error": "Открой панель через SSH-туннель."})
        if self.path == "/":
            return self.respond(200, PANEL.read_bytes(), "text/html")
        if self.path != "/api/status":
            return self.respond(404, {"error": "Страница не найдена."})
        with database() as conn:
            settings = get(conn, "settings", DEFAULTS)
            status = get(conn, "worker", {"state": "starting"})
            events = conn.execute("""
                SELECT sender, subject, status, detail, updated
                FROM messages ORDER BY updated DESC, id DESC LIMIT 50
            """).fetchall()
        self.respond(200, {"mailbox": MAILBOX, "settings": settings, "worker": status,
                           "events": [dict(row) for row in events]})

    def do_POST(self):
        if not self.allowed() or self.headers.get("Origin") != "http://127.0.0.1:8787":
            return self.respond(403, {"error": "Запрос разрешён только из панели."})
        if self.path != "/api/settings":
            return self.respond(404, {"error": "Страница не найдена."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32_768 or self.headers.get_content_type() != "application/json":
                raise ValueError("Проверь формат запроса.")
            settings = valid_settings(json.loads(self.rfile.read(length)))
        except (ValueError, UnicodeError) as error:
            return self.respond(400, {"error": str(error)})
        with database() as conn:
            put(conn, "settings", settings)
        self.respond(200, settings)


if __name__ == "__main__":
    if not ADDRESS.fullmatch(MAILBOX):
        sys.exit("Set MAILBOT_ADDRESS to a valid mailbox address")
    valid_settings(DEFAULTS)
    init()
    if sys.argv[1:] == ["worker"]:
        worker()
    elif sys.argv[1:] == ["admin"]:
        ThreadingHTTPServer(("0.0.0.0", 8787), Admin).serve_forever()
    else:
        sys.exit("Specify worker or admin")
