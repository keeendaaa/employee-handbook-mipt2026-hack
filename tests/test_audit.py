from navigator.audit import audit_documents


def test_audit_counts_formula_errors_and_ocr_without_claiming_completeness():
    docs = [{"document_id": "synthetic", "version_id": "v1", "name": "test.xlsx", "warnings": ["formula"],
             "blocks": [{"text": "Синтетический пример", "metadata": {"cells": [
                 {"formula": "=SUM(#REF!)", "cached_value": None, "cache_verified": False}]}},
                        {"text": "Тест", "method": "ocr", "metadata": {"ocr_rotation": 90}}]}]
    report = audit_documents(docs)
    assert report["totals"]["broken_formula_references"] == 1
    assert report["totals"]["missing_formula_cache"] == 1
    assert report["totals"]["rotated_pages"] == 1
    assert not report["normative_completeness_verified"]
