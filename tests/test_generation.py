"""Synthetic external-API responses: citation failures must not become answers."""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from navigator.api import create_app
from navigator.generation import Generator, GenerationError
from navigator.sources import reference


def fixture():
    doc = {"document_id": "demo", "version_id": "a" * 64, "name": "Синтетический документ", "sha256": "b" * 64,
           "warnings": [], "blocks": [{"text": "3.2. Заявку подать до 16:00.\nЗатем дождаться согласования.", "locator": {"page": 2}}]}
    ref = reference(doc, 0, 0, len(doc["blocks"][0]["text"]))
    retrieved = {"corpus_revision": "test", "results": [{"citation": ref}], "unrepresented_query_parts": []}
    answer = {"result_type": "answered", "summary": [{"text": "Подайте заявку до 16:00.", "citation_ids": [ref["source_id"]]}],
              "steps": [], "missing_information": [], "clarifications": [], "conflicts": []}
    return doc, retrieved, answer


def generate(body, *, status=200):
    def handler(request):
        assert request.headers["authorization"] == "Bearer synthetic-key"
        # Fixture source is an exact slice; simulate the model using the short handle it received.
        ref = fixture()[1]["results"][0]["citation"]
        content = json.dumps(body).replace(ref["source_id"], "S1")
        return httpx.Response(status, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                            "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    return Generator("synthetic-key", transport=httpx.MockTransport(handler))


def test_answer_uses_canonical_quote_and_reports_cost():
    _, retrieved, answer = fixture()
    result = generate(answer).answer("Когда подать?", retrieved)
    assert result["citations"] == [retrieved["results"][0]["citation"]]
    assert result["usage"]["cost_usd_estimate"] == .0001
    assert result["model"] == "Qwen/Qwen3.8-27B"


@pytest.mark.parametrize("failure", ["unknown_source", "no_citations", "incomplete", "false_not_found"])
def test_unverifiable_or_inconsistent_answer_is_rejected(failure):
    _, retrieved, answer = fixture()
    if failure == "unknown_source": answer["summary"][0]["citation_ids"] = ["invented"]
    if failure == "no_citations": answer["summary"][0]["citation_ids"] = []
    if failure == "incomplete": retrieved["unrepresented_query_parts"] = [1]
    if failure == "false_not_found": answer["result_type"] = "not_found"
    with pytest.raises(GenerationError):
        generate(answer).answer("Вопрос", retrieved)


def test_api_failure_is_not_absence_of_information():
    _, retrieved, answer = fixture()
    with pytest.raises(GenerationError, match="HTTP 401"):
        generate(answer, status=401).answer("Вопрос", retrieved)


def test_partial_and_not_found_have_explicit_missing_information():
    _, retrieved, answer = fixture()
    answer.update(result_type="partial", missing_information=["Не найдена форма заявки."])
    assert generate(answer).answer("Вопрос", retrieved)["result_type"] == "partial"
    answer.update(result_type="not_found", summary=[])
    assert generate(answer).answer("Вопрос", retrieved)["citations"] == []


def test_http_validation_sources_and_model_failure():
    doc, retrieved, answer = fixture()
    store = SimpleNamespace(document=lambda version: doc, active_revision=lambda: {"corpus_key": "test"})
    service = SimpleNamespace(store=store, search=lambda *args, **kwargs: retrieved)
    with TestClient(create_app(service=service, generator=generate(answer, status=401))) as client:
        assert client.get("/").status_code == 200
        assert client.post("/api/ask", json={"question": " "}).status_code == 422
        assert client.post("/api/search", json={"question": "Вопрос", "limit": True}).status_code == 422
        assert client.post("/api/ask", json={"question": "Вопрос"}).status_code == 502
        ref = retrieved["results"][0]["citation"]
        data = client.get("/api/sources/" + ref["source_id"]).json()
        assert data["quote"] == ref["quote"]
        assert data["line_end"] == 2
        assert client.get("/api/sources/invented").status_code == 404


def test_truncated_answer_retries_and_accounts_for_both_requests():
    _, retrieved, answer = fixture()
    attempts = []
    def handler(request):
        attempts.append(request)
        first = len(attempts) == 1
        content = "" if first else json.dumps(answer).replace(retrieved['results'][0]['citation']['source_id'], "S1")
        return httpx.Response(200, json={"choices": [{"finish_reason": "length" if first else "stop", "message": {"content": content}}],
                                        "usage": {"prompt_tokens": 100, "completion_tokens": 5000 if first else 20}})
    result = Generator("synthetic-key", transport=httpx.MockTransport(handler)).answer("Вопрос", retrieved)
    assert len(attempts) == 2
    assert result['usage']['completion_tokens'] == 5020
    assert result['usage']['prompt_tokens'] == 200
    assert result['citations'][0]['source_id'] == retrieved['results'][0]['citation']['source_id']


def test_temporary_provider_outage_retries_once(monkeypatch):
    monkeypatch.setattr('navigator.generation.time.sleep', lambda seconds: None)
    _, retrieved, answer = fixture()
    attempts = []
    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"message": "temporarily unavailable"}})
        content = json.dumps(answer).replace(retrieved['results'][0]['citation']['source_id'], "S1")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": {}})
    result = Generator("synthetic-key", transport=httpx.MockTransport(handler)).answer("Вопрос", retrieved)
    assert result['result_type'] == 'answered'
    assert len(attempts) == 2


def test_persistent_provider_outage_stays_a_technical_error(monkeypatch):
    monkeypatch.setattr('navigator.generation.time.sleep', lambda seconds: None)
    _, retrieved, answer = fixture()
    attempts = []
    def handler(request):
        attempts.append(request)
        return httpx.Response(503, json={"error": {"message": "temporarily unavailable"}})
    with pytest.raises(GenerationError, match='HTTP 503'):
        Generator('synthetic-key', transport=httpx.MockTransport(handler)).answer('Вопрос', retrieved)
    assert len(attempts) == 2


def test_not_found_discards_uncited_model_elaboration_and_empty_search_skips_model():
    from navigator.generation import NOT_FOUND_INFORMATION
    _, retrieved, answer = fixture()
    answer.update(result_type='not_found', summary=[], missing_information=['Единственное упоминание отпуска — в командировках.'])
    generator = generate(answer)
    result = generator.answer('Как оформить отпуск?', retrieved)
    assert result['missing_information'] == [NOT_FOUND_INFORMATION]
    assert result['summary'] == result['steps'] == result['citations'] == []
    generator.close()
    # A closed client would fail if this path attempted an external call.
    retrieved['results'] = []
    assert generator.answer('Вопрос', retrieved)['missing_information'] == [NOT_FOUND_INFORMATION]


@pytest.mark.parametrize('field', ['clarifications', 'conflicts'])
def test_not_found_cannot_smuggle_facts_in_other_fields(field):
    _, retrieved, answer = fixture()
    answer.update(result_type='not_found', summary=[], missing_information=['Не найдено.'])
    answer[field] = ['Неподтверждённое дополнение']
    with pytest.raises(GenerationError):
        generate(answer).answer('Вопрос', retrieved)


def test_partial_keeps_specific_missing_information():
    _, retrieved, answer = fixture()
    answer.update(result_type='partial', missing_information=['В найденных фрагментах не найдена форма заявки.'])
    result = generate(answer).answer('Вопрос', retrieved)
    assert result['missing_information'] == answer['missing_information']
    assert result['citations'] == [retrieved['results'][0]['citation']]
