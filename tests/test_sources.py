"""Synthetic citation integrity and stable source locations."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from navigator.sources import reference, resolve, verify


def document():
    return {"document_id": "synthetic", "version_id": "a" * 64, "name": "Синтетический регламент",
            "sha256": "f" * 64, "warnings": [], "blocks": [{
                "text": "3.2. Тестовая заявка подаётся до 16:00.\nВторая строка уточняет условие.\n3.3. Другое правило.",
                "locator": {"page": 2}, "method": "native"}]}


def test_quote_has_exact_offsets_lines_and_section():
    doc = document()
    start = doc["blocks"][0]["text"].index("Тестовая")
    end = doc["blocks"][0]["text"].index("3.3.")
    ref = reference(doc, 0, start, end)
    assert ref["quote"] == doc["blocks"][0]["text"][start:end]
    assert (ref["line_start"], ref["line_end"]) == (1, 2)
    assert ref["section_labels"] == ["3.2"]
    assert ref["line_basis"] == "extracted_block"
    assert verify(doc, ref)


@pytest.mark.parametrize("field,value", [("quote", "Выдуманный срок"), ("locator", {"page": 99}),
                                         ("line_start", 12), ("version_id", "b" * 64)])
def test_tampered_quote_locator_lines_or_version_is_rejected(field, value):
    doc = document()
    ref = reference(doc, 0, 0, 15)
    ref[field] = value
    assert not verify(doc, ref)


def test_old_version_resolves_without_using_current_corpus():
    old = document()
    def get_doc(version):
        assert version == old["version_id"]
        return old
    ref = reference(old, 0, 5, 20)
    opened = resolve(SimpleNamespace(document=get_doc), ref["source_id"])
    assert opened["quote"] == ref["quote"]
    assert opened["block_text"] == old["blocks"][0]["text"]


def test_mutating_reference_does_not_mutate_authoritative_source():
    doc = document()
    ref = reference(doc, 0, 0, 15)
    ref["locator"]["page"] = 99
    assert doc["blocks"][0]["locator"] == {"page": 2}
    assert not verify(doc, ref)


def test_missing_number_is_not_invented_and_ocr_is_unverified():
    doc = document()
    doc["blocks"][0].update(text="Срок подачи не указан.\nТекст распознан OCR.", method="ocr")
    ref = reference(doc, 0, 0, 20)
    assert ref["section_labels"] == []
    assert ref["section_verification"] == "ocr_unverified"
    with pytest.raises(ValueError):
        resolve(None, "../../secret:1:2:3")
