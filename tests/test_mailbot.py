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

    def process(self, body, subtype="plain"):
        message = EmailMessage()
        message["From"] = SENDER
        message["Subject"] = "Тема письма"
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
        self.assertEqual(json.loads(request.data), {"question": QUESTION})
        open_request.assert_called_once()
        send = smtp.SMTP.return_value.__enter__.return_value.send_message
        send.assert_called_once()
        reply = send.call_args.args[0]
        self.assertEqual(reply["To"], SENDER)
        self.assertEqual(reply["In-Reply-To"], "<original@example.org>")
        text = reply.get_content()
        self.assertIn("1. Заполните форму заявки. [1]", text)
        self.assertIn("Срок рассмотрения не найден.", text)
        self.assertIn("Тестовый регламент (п. 3.1, стр. 2", text)
        self.assertIn("https://navigator.example.org/api/sources/version%3A0%3A0%3A20", text)

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
            "question": "Как оформить пропуск для прессы?\nВизит завтра в 15:00.",
        })
        self.assertIn("Источники", deliver.call_args.args[5])

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
        self.process("  ")
        opener.assert_not_called()
        self.assertIn("Напиши вопрос в тексте письма.", deliver.call_args.args[5])

    @patch.object(app, "deliver")
    @patch.object(navigator_client, "build_opener")
    def test_rate_limit_and_unavailable_backend_stay_in_queue(self, opener, deliver):
        for status in (429, 503):
            with self.subTest(status=status):
                with app.database() as conn:
                    conn.execute("DELETE FROM messages")
                open_request = opener.return_value.open
                open_request.reset_mock()
                open_request.side_effect = HTTPError(URL, status, "", {"Retry-After": "1200"}, None)
                self.process(QUESTION)
                self.process(QUESTION)
                open_request.assert_called_once()
                deliver.assert_not_called()
                with app.database() as conn:
                    row = conn.execute("SELECT status, detail FROM messages").fetchone()
                self.assertEqual(tuple(row), ("retry", f"Навигатор · HTTP {status}"))
