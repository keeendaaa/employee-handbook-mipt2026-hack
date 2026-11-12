"""Exact, versioned quote references, ready for a future source viewer."""

import re
from copy import deepcopy

SECTION = re.compile(r"(?m)^\s*(\d{1,3}(?:\.\d{1,3}){0,5})\.\s+|^\s*(\d{1,3}(?:\.\d{1,3}){1,5})\s+")
SOURCE_ID = re.compile(r"([a-f0-9]{64}):(\d{1,7}):(\d{1,10}):(\d{1,10})\Z")


def reference(document: dict, block_index: int, start: int, end: int) -> dict:
    if not isinstance(block_index, int) or not 0 <= block_index < len(document["blocks"]):
        raise ValueError("Блок источника отсутствует")
    block = document["blocks"][block_index]
    text = block["text"]
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
        raise ValueError("Некорректный диапазон цитаты")
    sections = list(SECTION.finditer(text[:end]))
    preceding = [m for m in sections if m.start() <= start]
    relevant = ([preceding[-1]] if preceding else []) + [m for m in sections if m.start() > start]
    labels = list(dict.fromkeys((m.group(1) or m.group(2)) for m in relevant))
    # OCR can place numbers in a separate column; never infer a missing section.
    return {
        "source_id": f"{document['version_id']}:{block_index}:{start}:{end}",
        "document_id": document["document_id"], "version_id": document["version_id"],
        "document_name": document["name"], "original_sha256": document["sha256"],
        "block_index": block_index, "locator": deepcopy(block["locator"]),
        "start": start, "end": end, "quote": text[start:end],
        "line_start": text.count("\n", 0, start) + 1,
        "line_end": text.count("\n", 0, end - 1) + 1,
        "line_basis": "extracted_block", "section_labels": labels,
        "extraction_method": block.get("method", "native"),
        "section_verification": "ocr_unverified" if block.get("method") == "ocr" else "extracted_not_semantically_verified",
    }


def resolve(store, source_id: str) -> dict:
    match = SOURCE_ID.fullmatch(source_id)
    if match is None:
        raise ValueError("Некорректный идентификатор источника")
    version_id, block, start, end = match.groups()
    doc = store.document(version_id)
    result = reference(doc, int(block), int(start), int(end))
    source = doc["blocks"][int(block)]
    # Viewer may number the whole block and highlight the exact quote.
    result["block_text"] = source["text"]
    result["extraction_warnings"] = doc["warnings"]
    return result


def verify(document: dict, citation: dict) -> bool:
    try:
        expected = reference(document, citation["block_index"], citation["start"], citation["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return all(citation.get(key) == value for key, value in expected.items())
