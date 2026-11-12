"""Evaluate evidence, not merely thematic document hits."""

from navigator.evaluation import evaluate


def fixtures():
    case = {"id": "S1", "question": "Синтетический вопрос", "expected_type": "answered", "split": "dev",
            "supports": [{"document_id": "test", "locator": {"page": 2}, "needle": "срок пять дней"}]}
    doc = {"document_id": "test", "blocks": [{"locator": {"page": 2}, "text": "Срок\nпять дней"}]}
    return case, doc


def test_right_document_wrong_passage_does_not_count_as_support():
    case, doc = fixtures()
    wrong = {"document_id": "test", "locator": {"page": 1}, "text": "Общие положения"}
    report = evaluate([case], lambda q, k: [wrong], [doc])
    assert report["document_recall_at_k"] == 1
    assert report["support_recall_at_k"] == 0
    assert report["missing_source_anchors"] == 0


def test_context_is_reported_separately_from_direct_hit():
    case, doc = fixtures()
    hit = {"document_id": "test", "locator": {"page": 1}, "text": "Другой пункт",
           "context_sources": [{"document_id": "test", "locator": {"page": 2}, "text": "Срок пять дней"}]}
    report = evaluate([case], lambda q, k: [hit], [doc])
    assert report["support_recall_at_k"] == 0
    assert report["context_support_recall_at_k"] == 1


def test_negative_and_technical_failure_are_not_successful_abstentions():
    case = {"id": "N1", "question": "Вне базы", "expected_type": "not_found", "supports": []}
    def unavailable(q, k):
        raise ConnectionError("private connection detail")
    report = evaluate([case], unavailable, [])
    assert report["technical_error_count"] == 1
    assert report["cases"][0]["technical_error"] == "ConnectionError"
    assert "private" not in str(report)
    assert report["cases"][0]["all_supports_found"] is None
    assert not report["answer_quality_evaluated"]
