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


def test_incremental_snapshot_reuses_vectors_and_rejects_stale_publish(store):
    from navigator.ingest.storage import IndexConflictError

    first = document()
    store.publish([first], [chunk(first)], model_revision='test', corpus_key='base')
    saved = store.snapshot_chunks('base')
    assert saved[0]['embedding'] == vector()
    second = document('synthetic-b', 'v2', 'Другой синтетический документ.')
    store.publish([first, second], saved + [chunk(second, 'c2', 1)],
                  model_revision='test', corpus_key='extended', expected_active='base')
    assert len(store.documents('extended')) == 2
    with pytest.raises(IndexConflictError):
        store.publish([first], saved, model_revision='test', corpus_key='stale', expected_active='base')
    assert store.active_revision()['corpus_key'] == 'extended'
    assert store.document(first['version_id']) == first


def test_import_queue_leases_recovery_and_source_url_privacy(store):
    from navigator.imports.download import ImportFailure
    from navigator.imports.repository import ImportRepository

    repo = ImportRepository(store)
    assert not repo.online()
    repo.heartbeat()
    assert repo.online()
    identifier = repo.create(source_url='https://example.org/file.pdf?token=synthetic')
    public = repo.get(identifier)
    assert public['status'] == 'queued' and 'source_url' not in public
    job = repo.claim()
    assert str(job['id']) == identifier and job['source_url'].endswith('synthetic')
    assert repo.claim() is None
    with store._connect() as conn:
        conn.execute("UPDATE import_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (identifier,))
    recovered = repo.claim()
    assert recovered['owner'] != job['owner']
    with pytest.raises(ImportFailure):
        repo.update(job, 'ready', 'Stale owner')
    repo.update(recovered, 'ready', 'Готово', filename='file.pdf')
    assert repo.get(identifier)['status'] == 'ready'
    with store._connect() as conn:
        assert conn.execute('SELECT source_url FROM import_jobs WHERE id=%s', (identifier,)).fetchone()['source_url'] is None
    for _ in range(5):
        repo.create(filename='test.pdf')
    with pytest.raises(ImportFailure, match='Очередь'):
        repo.create(filename='extra.pdf')


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


def test_shared_map_questions_keep_latest_checked_revision(store):
    from navigator.knowledge.repository import QuestionRepository
    doc=document()
    store.publish([doc],[chunk(doc)],model_revision='test',corpus_key='before')
    repo=QuestionRepository(store)
    answer={'corpus_revision':'before','result_type':'not_found','summary':[],'steps':[],'citations':[],
            'missing_information':['В найденных фрагментах ответ не найден.'],'clarifications':[],'conflicts':[]}
    repo.save('Синтетический вопрос?',answer,vector(),'test')
    repo.save('синтетический вопрос?',answer,vector(),'test')
    rows=repo.list();assert len(rows)==1 and rows[0]['corpus_key']=='before'
    store.publish([doc],[chunk(doc)],model_revision='test',corpus_key='after')
    answer['corpus_revision']='after'
    repo.save('Синтетический вопрос?',answer,vector(),'test')
    rows=repo.list();assert len(rows)==1 and rows[0]['corpus_key']=='after'
    assert rows[0]['query_vector']==vector()
    answer['result_type']='technical_error'
    with pytest.raises(ValueError):repo.save('Ошибка?',answer,vector(),'test')
    assert len(repo.list())==1
