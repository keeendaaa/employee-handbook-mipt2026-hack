"""Call the Navigator API for incoming mail."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .reply_format import format_answer

ASK_PATH = "/api/ask"
MAIL_ANALYSIS_PATH = "/api/mail/analyze"
DEFAULT_URL = "https://smena-mipt.ru" + MAIL_ANALYSIS_PATH
NO_ACTION_REPLY = "Письмо получено. Ситуаций, требующих помощи по регламентам, не обнаружено."
QUESTION_LIMIT = 20_000
RESPONSE_LIMIT = 2_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NavigatorError(RuntimeError):
    def __init__(self, detail, *, retry_after=None):
        super().__init__(detail)
        self.retry_after = retry_after


def ask(url, body, *, subject="", reply_without_issue=False):
    text = body.strip()
    subject = subject.strip()
    if not (subject or text):
        return NO_ACTION_REPLY if reply_without_issue else None
    if len(text) > QUESTION_LIMIT:
        return "Сократи текст письма до 20 000 символов, чтобы бот смог его разобрать."

    origin = urlsplit(url)
    prefix = origin.path.removesuffix(ASK_PATH).removesuffix(MAIL_ANALYSIS_PATH)
    endpoint = origin._replace(path=prefix + MAIL_ANALYSIS_PATH).geturl()
    request = Request(
        endpoint,
        data=json.dumps({"subject": subject, "body": text}, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=310) as response:
            raw = response.read(RESPONSE_LIMIT + 1)
    except HTTPError as error:
        delay = error.headers.get("Retry-After", "")
        retry_after = min(3600, int(delay)) if delay.isascii() and delay.isdecimal() and len(delay) <= 10 else 0
        if error.code == 429:
            retry_after = max(900, retry_after)
        elif error.code == 404:
            retry_after = max(300, retry_after)
        elif error.code not in {408, 500, 502, 503, 504}:
            retry_after = None
        raise NavigatorError(f"HTTP {error.code}", retry_after=retry_after) from None
    except (URLError, OSError) as error:
        raise NavigatorError("Нет соединения с API", retry_after=0) from error

    try:
        if len(raw) > RESPONSE_LIMIT:
            raise ValueError("Слишком большой ответ")
        answer = json.loads(raw)
        if answer == {"result_type": "no_action"}:
            return NO_ACTION_REPLY if reply_without_issue else None
        return format_answer(answer, endpoint, subject)
    except (KeyError, TypeError, ValueError) as error:
        raise NavigatorError("Некорректный ответ API") from error
