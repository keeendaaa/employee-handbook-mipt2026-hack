"""Render the same structured answer as HTML and plain text."""

from dataclasses import dataclass
from html import escape
from urllib.parse import quote, urlsplit, urlunsplit


@dataclass(frozen=True)
class MailReply:
    text: str
    html: str


@dataclass(frozen=True)
class Source:
    label: str
    url: str
    lines: str


@dataclass(frozen=True)
class Entry:
    text: str
    sources: tuple[Source, ...] = ()


@dataclass(frozen=True)
class Section:
    title: str
    entries: list[Entry]
    numbered: bool = False


GENERIC_MISSING = {
    "В индексе не найдены фрагменты для ответа.",
    "В найденных фрагментах ответ на вопрос не найден.",
    "В найденных фрагментах не удалось подтвердить ответ на вопрос.",
}
HEADLINES = {
    "answered": "Что важно по регламенту",
    "partial": "Что удалось подтвердить",
    "needs_clarification": "Нужно уточнение",
    "conflict": "В документах есть расхождения",
}


def source_link(source, origin, prefix, host):
    document = source["document_name"]
    locator = source["locator"]
    location = [f"стр. {locator['page']}"] if "page" in locator else []
    if "sheet" in locator:
        location.append(f"лист «{locator['sheet']}»")
    if "range" in locator:
        location.append(f"ячейки {locator['range']}")
    elif not location and "block" in locator:
        location.append(f"блок {locator['block']}")
    label = ", ".join([document, *location])
    path = f"{prefix}/api/sources/{quote(source['source_id'], safe='')}"
    url = urlunsplit((origin.scheme, host, path, "", ""))
    return Source(label, url, f"строки {source['line_start']}–{source['line_end']}")


def format_answer(answer, url, subject=""):
    result = answer["result_type"]
    heading = HEADLINES[result]
    origin = urlsplit(url)
    prefix = origin.path.removesuffix("/api/mail/analyze").removesuffix("/api/ask")
    host = origin.netloc
    if origin.scheme == "http" and origin.hostname == "host.docker.internal":
        host = "127.0.0.1" + (f":{origin.port}" if origin.port else "")
    sources = {item["source_id"]: source_link(item, origin, prefix, host)
               for item in answer.get("citations", [])}

    def claims(items):
        entries = []
        seen = set()
        for claim in items:
            text = claim["text"].strip()
            refs = tuple(dict.fromkeys(sources[source_id] for source_id in claim["citation_ids"]))
            if not text or not refs:
                raise ValueError("Неполное утверждение")
            if text.casefold() not in seen:
                entries.append(Entry(text, refs))
                seen.add(text.casefold())
        return entries

    summary = claims(answer.get("summary", []))
    steps = claims(answer.get("steps", []))
    missing = [Entry(item.strip()) for item in answer["missing_information"]
               if item.strip() and item.strip() not in GENERIC_MISSING]
    clarifications = [Entry(text) for text in answer.get("clarifications", [])]
    conflicts = [Entry(text) for text in answer.get("conflicts", [])]
    intro = f"Навигатор разобрал письмо «{subject}»." if subject else "Навигатор разобрал твоё письмо."
    if result == "needs_clarification":
        intro += " Для выбора порядка действий нужна дополнительная информация."
        brief, clarifications = clarifications[:1], clarifications[1:]
    elif result == "conflict":
        intro += " При проверке нашлись разные требования к одной ситуации."
        brief, conflicts = conflicts[:1], conflicts[1:]
    else:
        if result == "partial":
            intro += " По этой задаче удалось подтвердить часть требований."
        else:
            intro += " По этой задаче нашлись требования в регламентах."
        brief, summary = summary[:2], summary[2:]

    sections = [
        Section("Порядок действий", steps, numbered=True),
        Section("Подробности", summary),
        Section("Каких сведений не хватает", missing),
        Section("Что уточнить", clarifications),
        Section("Расхождения в документах", conflicts),
    ]
    return render(heading, intro, brief, sections)


def source_anchor(source, label):
    return f'<a href="{escape(source.url)}" style="color:#125479;">{escape(label)}</a>'


def text_entry(entry):
    labels = ", ".join(dict.fromkeys(source.label for source in entry.sources))
    return f"{entry.text}\nПо документу {labels}" if labels else entry.text


def html_entry(entry):
    grouped = {}
    for source in entry.sources:
        grouped.setdefault(source.label, []).append(source)
    links = []
    for label, fragments in grouped.items():
        if len(fragments) == 1:
            links.append(source_anchor(fragments[0], label))
        else:
            anchors = ", ".join(source_anchor(source, source.lines) for source in fragments)
            links.append(f"{escape(label)} · {anchors}")
    notes = ('<div style="font-size:13px;line-height:1.5;margin-top:4px;">'
             + " · ".join(links) + "</div>") if links else ""
    return escape(entry.text).replace("\n", "<br>") + notes


def render(heading, intro, brief, sections):
    text = [intro, heading + ("\n" + "\n".join(text_entry(item) for item in brief) if brief else "")]
    html = [
        '<!doctype html><html lang="ru"><head><meta charset="utf-8"></head><body>',
        '<div style="max-width:680px;margin:0 auto;padding:24px 16px;'
        'font-family:Arial,sans-serif;font-size:16px;line-height:1.55;color:#152f38;">',
        '<p style="margin:0 0 16px;color:#405c69;">' + escape(intro) + '</p>',
        '<div style="background:#eaf3f7;border-left:4px solid #125479;padding:16px;">'
        '<h1 style="font-size:22px;line-height:1.3;margin:0;">' + escape(heading) + '</h1>',
    ]
    for item in brief:
        html.append('<div style="margin-top:10px;">' + html_entry(item) + "</div>")
    html.append("</div>")
    all_sources = list(dict.fromkeys(source for item in brief for source in item.sources))
    for section in sections:
        if not section.entries:
            continue
        lines = []
        tag = "ol" if section.numbered else "ul"
        html.append(f'<h2 style="font-size:18px;margin:22px 0 8px;">{escape(section.title)}</h2>'
                    f'<{tag} style="margin:0;padding-left:22px;">')
        for index, item in enumerate(section.entries, 1):
            marker = f"{index}. " if section.numbered else "• "
            lines.append(marker + text_entry(item))
            html.append('<li style="margin:0 0 10px;">' + html_entry(item) + "</li>")
            all_sources.extend(item.sources)
        html.append(f"</{tag}>")
        text.append(section.title + "\n" + "\n".join(lines))
    if all_sources:
        text.append("Источники\n" + "\n".join(
            f"{source.label}\n{source.url}" for source in dict.fromkeys(all_sources)
        ))
    html.append("</div></body></html>")
    return MailReply("\n\n".join(text), "".join(html))
