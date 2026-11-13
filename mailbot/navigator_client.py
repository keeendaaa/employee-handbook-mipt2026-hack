"""Convert a Navigator answer into a reply with numbered source references."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ASK_PATH = "/api/ask"
MAIL_ANALYSIS_PATH = "/api/mail/analyze"
DEFAULT_URL = "https://smena-mipt.ru" + MAIL_ANALYSIS_PATH
NO_ACTION_REPLY = "Письмо получено. Ситуаций, требующих помощи по регламентам, не обнаружено."
QUESTION_LIMIT = 20_000
RESPONSE_LIMIT = 2_000_000
ANSWER_TYPES = {
    "answered": "",
    "partial": "В найденных фрагментах есть ответ на часть вопроса.",
    "needs_clarification": "Для ответа нужно уточнение.",
    "conflict": "В источниках найдены противоречащие друг другу положения.",
}

GENERIC_MISSING_INFORMATION = {
    "В индексе не найдены фрагменты для ответа.",
    "В найденных фрагментах ответ на вопрос не найден.",
    "В найденных фрагментах не удалось подтвердить ответ на вопрос.",
}


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
        return format_answer(answer, endpoint)
    except (KeyError, TypeError, ValueError) as error:
        raise NavigatorError("Некорректный ответ API") from error


def format_answer(answer, url):
    if answer["result_type"] == "not_found":
        missing = [item.strip() for item in answer["missing_information"]
                   if item.strip() and item.strip() not in GENERIC_MISSING_INFORMATION]
        sections = ["По найденным регламентам не удалось подтвердить порядок действий в этой ситуации."]
        if missing:
            sections.append("Каких сведений не хватает\n" + "\n".join(missing))
        sections.append(
            "Если вопрос срочный, уточни порядок и сроки у сотрудника, который ведёт этот вопрос. "
            "Если у тебя есть ссылка на применимый регламент, пришли её вместе с вопросом, "
            "чтобы было понятно, какой документ искать в базе."
        )
        return "\n\n".join(sections)

    status = ANSWER_TYPES[answer["result_type"]]
    sources = {source["source_id"]: source for source in answer["citations"]}
    numbers = {}

    def format_claim(claim):
        refs = claim["citation_ids"]
        if not refs:
            raise ValueError("У утверждения нет источников")
        links = []
        for source_id in refs:
            sources[source_id]
            number = numbers.setdefault(source_id, len(numbers) + 1)
            links.append(f"[{number}]")
        return f"{claim['text']} {' '.join(links)}"

    sections = [
        (None, [status] if status else []),
        ("Краткий ответ", [format_claim(claim) for claim in answer["summary"]]),
        ("Порядок действий", [
            f"{index}. {format_claim(step)}" for index, step in enumerate(answer["steps"], 1)
        ]),
        ("Каких сведений не хватает", answer["missing_information"]),
        ("Что уточнить", answer["clarifications"]),
        ("Противоречия", answer["conflicts"]),
    ]
    origin = urlsplit(url)
    prefix = origin.path.removesuffix(MAIL_ANALYSIS_PATH).removesuffix(ASK_PATH)
    citations = []
    for source_id, number in numbers.items():
        source = sources[source_id]
        locator = source["locator"]
        location = [f"п. {label}" for label in source["section_labels"]]
        for key, label in (("page", "стр."), ("block", "блок"), ("table", "таблица"),
                           ("sheet", "лист"), ("row", "строка"), ("range", "ячейки")):
            if key in locator:
                location.append(f"{label} {locator[key]}")
        location.append(f"строки извлечённого текста {source['line_start']}–{source['line_end']}")
        if source["extraction_method"] == "ocr":
            location.append("распознано со скана")
        source_path = f"{prefix}/api/sources/{quote(source_id, safe='')}"
        link = urlunsplit((origin.scheme, origin.netloc, source_path, "", ""))
        citations.append(f"[{number}] {source['document_name']} ({', '.join(location)})\n"
                         f"«{source['quote']}»\n{link}")
    sections.append(("Источники", citations))
    rendered = ["\n".join(([title] if title else []) + lines) for title, lines in sections if lines]
    if not rendered:
        raise ValueError("Пустой ответ")
    return "\n\n".join(rendered)
