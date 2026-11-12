"""Source-anchored retrieval evaluation, with no generated answers or verdicts."""

import re
import hashlib
import json
from datetime import datetime, timezone
from time import perf_counter


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def score_case(case: dict, results: list[dict], documents: list[dict], k: int) -> dict:
    expected = case.get("supports", [])
    source_by_id = {d["document_id"]: d for d in documents}
    hits, context_hits, available, ranks = [], [], [], []
    for support in expected:
        needle = normalize(support["needle"])
        def matches(source):
            return (source["document_id"] == support["document_id"]
                    and source["locator"] == support["locator"]
                    and needle in normalize(source["text"]))
        positions = [rank for rank, result in enumerate(results[:k], 1) if matches(result)]
        hits.append(bool(positions))
        ranks.append(positions[0] if positions else None)
        context_hits.append(any(matches(context) for result in results[:k]
                                for context in result.get("context_sources", [])))
        document = source_by_id.get(support["document_id"], {})
        available.append(any(block["locator"] == support["locator"]
                             and needle in normalize(block["text"])
                             for block in document.get("blocks", [])))
    expected_docs = {s["document_id"] for s in expected}
    actual_docs = {r["document_id"] for r in results[:k]}
    positive = bool(expected)
    return {
        "id": case["id"], "split": case.get("split", "dev"),
        "expected_type": case["expected_type"], "tags": case.get("tags", []),
        "support_count": len(expected), "support_hits": sum(hits),
        "context_support_hits": sum(a or b for a, b in zip(hits, context_hits)),
        "available_supports": sum(available), "support_ranks": ranks,
        "document_recall": len(expected_docs & actual_docs) / len(expected_docs) if positive else None,
        "all_supports_found": all(hits) if positive else None,
        "all_context_supports_found": all(a or b for a, b in zip(hits, context_hits)) if positive else None,
        "reciprocal_rank": 1 / min(r for r in ranks if r) if any(ranks) else 0.0 if positive else None,
        "candidate_count": len(results),
        "answer_type_evaluated": False,
        "negative_handling": "not_assessed_without_answer_layer" if not positive else None,
    }


def evaluate(cases: list[dict], retrieve, documents: list[dict], k: int = 10) -> dict:
    if not cases or not 1 <= k <= 100:
        raise ValueError("Нужны непустой набор вопросов и k от 1 до 100")
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Повторяются ID вопросов")
    rows = []
    for case in cases:
        if case.get("expected_type") not in {"answered", "partial", "not_found", "conflict", "needs_clarification"}:
            raise ValueError("Некорректный expected_type")
        if not case.get("question", "").strip():
            raise ValueError("Пустой вопрос в проверочном наборе")
        started = perf_counter()
        technical_error = None
        try:
            results = retrieve(case["question"], k)
        except Exception as exc:
            # A failed query is separately recorded, never labelled not_found.
            technical_error = type(exc).__name__
            results = []
        row = score_case(case, results, documents, k)
        row["technical_error"] = technical_error
        row["latency_seconds"] = round(perf_counter() - started, 3)
        rows.append(row)
    positives = [r for r in rows if r["support_count"]]
    supports = sum(r["support_count"] for r in positives)
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_digest": hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "k": k, "case_count": len(rows), "positive_count": len(positives),
        "negative_count": len(rows) - len(positives),
        "technical_error_count": sum(bool(r["technical_error"]) for r in rows),
        "document_recall_at_k": sum(r["document_recall"] for r in positives) / len(positives) if positives else None,
        "support_recall_at_k": sum(r["support_hits"] for r in positives) / supports if supports else None,
        "context_support_recall_at_k": sum(r["context_support_hits"] for r in positives) / supports if supports else None,
        "all_supports_rate": sum(r["all_supports_found"] for r in positives) / len(positives) if positives else None,
        "mrr_at_k": sum(r["reciprocal_rank"] for r in positives) / len(positives) if positives else None,
        "missing_source_anchors": supports - sum(r["available_supports"] for r in positives),
        "answer_quality_evaluated": False, "cases": rows,
    }
