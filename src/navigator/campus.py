"""Campus names supplied by the user: search hints, never regulatory evidence."""

import re


CAMPUS_NAMES = {
    "нк": "новый корпус",
    "кпм": "корпус прикладной математики",
    "гк": "главный корпус",
    "цифра": "Физтех Цифра",
    "арктика": "Арктика",
}
TOKEN = re.compile(r"(?<!\w)(кпм|нк|гк|цифр(?:а|е|у|ы|ой)|арктик(?:а|е|у|и|ой))(?!\w)", re.I)
LOCATION = re.compile(r"\b(?:корпус\w*|здани\w*|аудитор\w*|кабинет\w*|попасть|дойти|пройти|пропуск\w*|вход\w*|посет\w*)\b", re.I)


def expand_campus_names(question: str) -> tuple[str, list[dict]]:
    """Keep the original separately; don't reinterpret ordinary digits or legal codes."""
    hints = []

    def replace(match):
        value = match.group().casefold()
        key = "цифра" if value.startswith("цифр") else "арктика" if value.startswith("арктик") else value
        if key in {"нк", "гк"} and re.match(r"\s+РФ\b", question[match.end():], re.I):
            return match.group()
        if key == "цифра":
            if re.search(r"физтех[\s-]+$", question[:match.start()], re.I):
                return match.group()
            preceding = question[max(0, match.start() - 45):match.start()]
            locative = re.search(r'\b(?:в|во|из)\s+[«"]?\s*$', preceding, re.I)
            if not locative and not (LOCATION.search(question) and
                                      (match.group()[0].isupper() or re.search(r'\b(?:к|у|до|около|возле)\s+[«"]?\s*$', preceding, re.I))):
                return match.group()
        hint = {"alias": match.group(), "name": CAMPUS_NAMES[key], "source": "user_glossary"}
        if not any(h["name"] == hint["name"] for h in hints):
            hints.append(hint)
        # Арктика already is the supplied name; do not add a redundant search route.
        return match.group() if key == "арктика" else CAMPUS_NAMES[key]

    expanded = TOKEN.sub(replace, question)
    return expanded, hints
