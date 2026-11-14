import io
import json
import unittest
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from mailbot import app, navigator_client


URL = "https://navigator.example.org/api/ask"
QUESTION = "Как подать заявку?"
SENDER = "employee@example.org"
SOURCE = {
    "source_id": "version:0:0:20",
    "document_name": "Тестовый регламент",
    "locator": {"page": 2},
    "section_labels": ["3.1"],
    "line_start": 4,
    "line_end": 5,
    "extraction_method": "native",
    "quote": "Заполните форму заявки.",
}
CLAIM = {"text": "Заполните форму заявки.", "citation_ids": [SOURCE["source_id"]]}
ANSWER = {
    "result_type": "partial",
    "summary": [CLAIM],
    "steps": [CLAIM],
    "missing_information": ["Срок рассмотрения не найден."],
    "clarifications": [],
    "conflicts": [],
    "citations": [SOURCE],
}


class MailbotIntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(app, "DATABASE", Path(directory) / "test.sqlite"))
        self.enterContext(patch.object(app, "MAILBOX", "bot@example.org"))
        self.enterContext(patch.object(app, "RESEND_KEY", Path(directory) / "unused"))
        app.init()
        self.settings = {"enabled": True, "senders": [], "api_url": URL}

    def process(self, body, subtype="plain", subject="Тема письма"):
        message = EmailMessage()
        message["From"] = SENDER
        message["Subject"] = subject
        message["Message-ID"] = "<original@example.org>"
        message.set_content(body, subtype=subtype)
        with patch.object(app, "read_message", return_value=(message, "")):
            app.process(None, 1, 42, self.settings, "unused", None)

    @patch.object(app, "smtplib")
    @patch.object(navigator_client, "build_opener")
    def test_plain_question_is_answered_with_citations_in_same_thread(self, opener, smtp):
        open_request = opener.return_value.open
        open_request.return_value.__enter__.return_value = io.BytesIO(json.dumps(ANSWER).encode())
        self.process(QUESTION)
        self.process(QUESTION)

        request = open_request.call_args.args[0]
        self.assertEqual(json.loads(request.data), {"subject": "Тема письма", "body": QUESTION})
        self.assertTrue(request.full_url.endswith("/api/mail/analyze"))
        open_request.assert_called_once()
        send = smtp.SMTP.return_value.__enter__.return_value.send_message
        send.assert_called_once()
        reply = send.call_args.args[0]
        self.assertEqual(reply["To"], SENDER)
        self.assertEqual(reply["In-Reply-To"], "<original@example.org>")
        self.assertEqual(reply.get_content_type(), "multipart/alternative")
        text = reply.get_body(("plain",)).get_content()
        html = reply.get_body(("html",)).get_content()
        self.assertTrue(text.startswith("Навигатор разобрал письмо «Тема письма»."))
        self.assertIn("1. Заполните форму заявки.", text)
        self.assertNotIn("[1]", text + html)
        self.assertLess(html.index("Что удалось подтвердить"), html.index("Порядок действий"))
        self.assertIn('href="https://navigator.example.org/api/sources/version%3A0%3A0%3A20"', html)
        self.assertIn("Срок рассмотрения не найден.", text)
        self.assertIn("Тестовый регламент, стр. 2", text)
        self.assertIn("https://navigator.example.org/api/sources/version%3A0%3A0%3A20", text)

    @patch.object(app, "deliver")
    @patch.object(navigator_client, "build_opener")
    def test_not_found_replies_once_with_a_next_step(self, opener, deliver):
        answer = {
            **ANSWER,
            "result_type": "not_found",
            "summary": [],
            "steps": [],
            "citations": [],
            "missing_information": ["В найденных фрагментах не удалось подтвердить ответ на вопрос."],
        }
        opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(
            json.dumps(answer).encode()
        )
        self.process("Нужно оформить пропуск для прессы.")
        reply = deliver.call_args.args[5].text
        self.assertNotIn("Каких сведений не хватает", reply)
        self.assertEqual(reply.count("не удалось подтвердить"), 1)
        self.assertIn("уточни порядок и сроки", reply)

    @patch.object(app, "deliver")
    @patch.object(navigator_client, "build_opener")
    def test_no_action_respects_panel_setting(self, opener, deliver):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                with app.database() as conn:
                    conn.execute("DELETE FROM messages")
                self.settings["reply_without_issue"] = enabled
                opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(
                    b'{"result_type":"no_action"}'
                )
                self.process("Спасибо, пропуск уже оформлен.")
                if enabled:
                    deliver.assert_called_once()
                else:
                    deliver.assert_not_called()
                    with app.database() as conn:
                        row = conn.execute("SELECT status FROM messages").fetchone()
                    self.assertEqual(row["status"], "skipped")

    @patch.object(app, "deliver")
    @patch.object(navigator_client, "build_opener")
    def test_html_only_email_passes_readable_question(self, opener, deliver):
        open_request = opener.return_value.open
        open_request.return_value.__enter__.return_value = io.BytesIO(json.dumps(ANSWER).encode())
        self.process(
            "<html><head><title>Почта</title><style>p { color: red }</style></head>"
            "<body><div>Как оформить <b>пропуск</b>&nbsp;для прессы?"
            "<br>Визит завтра в 15:00.</div><script>ignored()</script></body></html>",
            subtype="html",
        )
        request = open_request.call_args.args[0]
        self.assertEqual(json.loads(request.data), {
            "subject": "Тема письма",
            "body": "Как оформить пропуск для прессы?\nВизит завтра в 15:00.",
        })
        self.assertIn("Источники", deliver.call_args.args[5].text)

    def test_plain_body_is_preferred_and_attachments_are_ignored(self):
        message = EmailMessage()
        message.set_content(QUESTION)
        message.add_alternative("<p>HTML-версия</p>", subtype="html")
        message.add_attachment("<p>Вложение</p>", subtype="html", filename="extra.html")
        self.assertEqual(app.extract_question(message), QUESTION)

        attachments_only = EmailMessage()
        attachments_only.add_attachment("<p>Вложение</p>", subtype="html", filename="extra.html")
        self.assertEqual(app.extract_question(attachments_only), "")

    @patch.object(app, "deliver")
    @patch.object(navigator_client, "build_opener")
    def test_empty_question_never_calls_backend(self, opener, deliver):
        self.process("  ", subject="")
        opener.assert_not_called()
        deliver.assert_not_called()

    @patch.object(app, "deliver")
    @patch.object(navigator_client, "build_opener")
    def test_rate_limit_and_unavailable_backend_stay_in_queue(self, opener, deliver):
        for status in (404, 429, 503):
            with self.subTest(status=status):
                with app.database() as conn:
                    conn.execute("DELETE FROM messages")
                open_request = opener.return_value.open
                open_request.reset_mock()
                open_request.side_effect = HTTPError(URL, status, "", {}, io.BytesIO())
                self.process(QUESTION)
                self.process(QUESTION)
                open_request.assert_called_once()
                deliver.assert_not_called()
                with app.database() as conn:
                    row = conn.execute("SELECT status, detail, retry_at FROM messages").fetchone()
                self.assertEqual((row["status"], row["detail"]), ("retry", f"Навигатор · HTTP {status}"))
                minimum_delay = {404: 300, 429: 900, 503: 30}[status]
                self.assertGreaterEqual(row["retry_at"], app.time.time() + minimum_delay - 1)
