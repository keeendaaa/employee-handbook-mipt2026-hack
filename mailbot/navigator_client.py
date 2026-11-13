"""Convert a Navigator answer into a reply with numbered source references."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_URL = "https://smena-mipt.ru/api/ask"
PUBLIC_DATA_CONFIRMATION = "Подтверждаю, что вопрос не содержит конфиденциальных данных."
QUESTION_LIMIT = 20_000
RESPONSE_LIMIT = 2_000_000
ANSWER_TYPES = {
    "answered": "",
    "partial": "В найденных фрагментах есть ответ на часть вопроса.",
    "not_found": "В найденных фрагментах ответ на вопрос не найден.",
    "needs_clarification": "Для ответа нужно уточнение.",
    "conflict": "В источниках найдены противоречащие друг другу положения.",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NavigatorError(RuntimeError):
    def __init__(self, detail, *, retry_after=None):
        super().__init__(detail)
        self.retry_after = retry_after


def ask(url, body):
    confirmation, _, question = body.strip().partition("\n")
    if confirmation.rstrip("\r") != PUBLIC_DATA_CONFIRMATION:
        return (
            "Чтобы задать вопрос по регламентам, отправь новое письмо. "
            "В первой строке напиши подтверждение ниже, со второй строки — сам вопрос. "
            "Вопрос передаётся внешней модели. Удали из письма личные данные и закрытую переписку.\n\n"
            + PUBLIC_DATA_CONFIRMATION
        )
    question = question.strip()
    if not question or len(question) > QUESTION_LIMIT:
        return "Введи вопрос после строки подтверждения. Длина вопроса — до 20 000 символов."

    request = Request(
        url,
        data=json.dumps({"question": question}, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=275) as response:
            raw = response.read(RESPONSE_LIMIT + 1)
    except HTTPError as error:
        delay = error.headers.get("Retry-After", "")
        retry_after = min(3600, int(delay)) if delay.isascii() and delay.isdecimal() and len(delay) <= 10 else 0
        if error.code == 429:
            retry_after = max(900, retry_after)
        elif error.code not in {408, 500, 502, 503, 504}:
            retry_after = None
        raise NavigatorError(f"HTTP {error.code}", retry_after=retry_after) from None
    except (URLError, OSError) as error:
        raise NavigatorError("Нет соединения с API", retry_after=0) from error

    try:
        if len(raw) > RESPONSE_LIMIT:
            raise ValueError("Слишком большой ответ")
        return format_answer(json.loads(raw), url)
    except (KeyError, TypeError, ValueError) as error:
        raise NavigatorError("Некорректный ответ API") from error


def format_answer(answer, url):
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
        prefix = origin.path.removesuffix("/api/ask")
        source_path = f"{prefix}/api/sources/{quote(source_id, safe='')}"
        link = urlunsplit((origin.scheme, origin.netloc, source_path, "", ""))
        citations.append(f"[{number}] {source['document_name']} ({', '.join(location)})\n"
                         f"«{source['quote']}»\n{link}")
    sections.append(("Источники", citations))
    rendered = ["\n".join(([title] if title else []) + lines) for title, lines in sections if lines]
    if not rendered:
        raise ValueError("Пустой ответ")
    return "\n\n".join(rendered)
