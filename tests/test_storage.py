"""Synthetic storage tests; integration requires a dedicated TEST_DATABASE_URL."""

import os
from uuid import uuid4

import pytest

from navigator.ingest.storage import IndexUnavailableError, Store, _vector_literal


def vector(axis=0):
    values = [0.0] * 384
    values[axis] = 1.0
    return values


@pytest.mark.parametrize("values", [[1.0], [0.0] * 384, [float("nan")] * 384, [float("inf")] * 384])
def test_reject_invalid_vectors(values):
    with pytest.raises(ValueError):
        _vector_literal(values)


def test_vector_literal():
    assert _vector_literal(vector()).startswith("[1.0,0.0,")


def document(document_id="synthetic-a", version_id="v1", text="Синтетический порядок: подайте заявку."):
    return {
        "document_id": document_id, "version_id": version_id, "sha256": "a" * 64,
        "name": "Синтетический документ", "blocks": [{"text": text, "locator": {"page": 1}}],
        "warnings": [],
    }


def chunk(doc, chunk_id="c1", axis=0):
    text = doc["blocks"][0]["text"]
    return {
        "document_id": doc["document_id"], "version_id": doc["version_id"],
        "chunk_id": chunk_id, "block_index": 0, "text": text, "start": 0, "end": len(text),
        "locator": {"page": 1}, "heading_path": [], "embedding": vector(axis),
    }


def test_bad_source_slice_rejected_before_database_connection():
    doc = document()
    item = chunk(doc)
    item["text"] = "Выдуманная цитата"
    with pytest.raises(ValueError, match="исходным блоком"):
        Store("unused").publish([doc], [item], model_revision="test", corpus_key="test")


def test_empty_corpus_rejected_before_database_connection():
    with pytest.raises(ValueError, match="Пустой корпус"):
        Store("unused").publish([], [], model_revision="test", corpus_key="test")


@pytest.mark.parametrize("field,replacement", [("locator", {"page": 99}), ("heading_path", ["Выдуманный раздел"])])
def test_forged_locator_or_heading_rejected_before_database_connection(field, replacement):
    doc = document()
    item = chunk(doc)
    item[field] = replacement
    with pytest.raises(ValueError, match="исходным блоком"):
        Store("unused").publish([doc], [item], model_revision="test", corpus_key="test")


def test_schema_is_available_as_package_resource():
    from importlib.resources import files

    assert "CREATE EXTENSION IF NOT EXISTS vector" in files("navigator.ingest").joinpath("schema.sql").read_text()


@pytest.fixture
def store():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL не задан; нужен отдельный PostgreSQL с pgvector")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    # The fixture only removes its own freshly created random schema.
    schema = "test_navigator_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        instance = Store(make_conninfo(dsn, options=f"-csearch_path={schema},public"))
        instance.init_schema()
        yield instance
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_publication_idempotency_snapshots_and_rollback(store):
    with pytest.raises(IndexUnavailableError):
        store.search("заявка", vector())
    first = document()
    first_chunk = chunk(first)
    store.publish([first], [first_chunk], model_revision="test", corpus_key="generation-1")
    store.publish([first], [first_chunk], model_revision="test", corpus_key="generation-1")
    assert store.active_revision()["corpus_key"] == "generation-1"
    assert len(store.search("заявка", vector())) == 1
    with pytest.raises(ValueError, match="модели"):
        store.search("заявка", vector(), model_revision="other-model")

    changed = document(version_id="v1", text="Изменённое содержание той же версии.")
    with pytest.raises(ValueError, match="Неизменяемая версия"):
        store.publish([changed], [chunk(changed, "c2")], model_revision="test", corpus_key="bad")
    assert store.active_revision()["corpus_key"] == "generation-1"

    second = document("synthetic-b", "v2", "Другой синтетический документ: оформите отпуск.")
    store.publish([second], [chunk(second, "c2", 1)], model_revision="test", corpus_key="generation-2")
    results = store.search("отпуск", vector(1))
    assert {row["version_id"] for row in results} == {"v2"}
    assert results[0]["corpus_revision"] == "generation-2"
    pinned = store.search("заявка", vector(), corpus_key="generation-1", model_revision="test")
    assert {row["version_id"] for row in pinned} == {"v1"}
    assert store.active_revision()["corpus_key"] == "generation-2"
    assert results[0]["extraction_warnings"] == []
    with store._connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"] == 2
        assert conn.execute("SELECT count(*) AS n FROM corpus_revisions").fetchone()["n"] == 2
    # Historical corpus can be activated again without rebuilding or losing refs.
    store.publish([first], [first_chunk], model_revision="test", corpus_key="generation-1")
    assert store.search("заявка", vector())[0]["version_id"] == "v1"


def test_scoped_lexical_search_prefers_distinct_terms_over_repetition(store):
    repeated = document("scoped", "scoped-v1", "Заявка " * 40)
    wanted_text = "Срок подачи заявки: до пятого мая. Ответственный отдел."
    repeated["blocks"].append({"text": wanted_text, "locator": {"page": 2}})
    wanted = dict(chunk(repeated, "wanted"), block_index=1, text=wanted_text, end=len(wanted_text), locator={"page": 2})
    other = document("unrelated", "other-v1", "Срок заявки отдел приказ")
    store.publish([repeated, other], [chunk(repeated, "repeated"), wanted, chunk(other, "other")],
                  model_revision="test", corpus_key="scope-test")
    rows = store.search("срок заявки отдел", vector(), mode="lexical", lexical_or=True, document_ids=["scoped"])
    assert rows[0]["chunk_id"] == "wanted"
    assert {r["document_id"] for r in rows} == {"scoped"}
    assert store.search("заявка", vector(), document_ids=[]) == []
