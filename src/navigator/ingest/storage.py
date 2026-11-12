"""Immutable source versions and atomically published local search corpora.

This module never opens network connections other than the explicitly configured
PostgreSQL connection. It does not emit document text or connection parameters.
"""

from __future__ import annotations

import math
from importlib.resources import files
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class IndexUnavailableError(RuntimeError):
    """No corpus has been published; this is not a negative search result."""


def _vector_literal(vector: list[float]) -> str:
    if len(vector) != 384:
        raise ValueError("Вектор должен содержать 384 числа")
    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Вектор содержит нечисловые или бесконечные значения")
    if not any(value != 0 for value in values):
        raise ValueError("Нулевой вектор нельзя использовать для cosine search")
    return "[" + ",".join(str(value) for value in values) + "]"


class Store:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        return psycopg.connect(self.dsn, connect_timeout=10, row_factory=dict_row)

    def init_schema(self) -> None:
        schema = files("navigator.ingest").joinpath("schema.sql")
        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(783419420)")
            conn.execute(schema.read_text(encoding="utf-8"))

    def publish(
        self,
        documents: list[dict],
        chunks: list[dict],
        *,
        model_revision: str,
        corpus_key: str,
    ) -> str:
        """Publish a complete snapshot, preserving all earlier snapshot sources.

        The caller must not invoke this method for an incomplete import. All
        validation and inserts happen before the active pointer is changed.
        A conflicting immutable ID causes rollback instead of silent mutation.
        """
        if not documents or not chunks:
            raise ValueError("Пустой корпус нельзя публиковать")
        if not model_revision or not corpus_key:
            raise ValueError("Нужны версия модели и ключ корпуса")
        versions = {doc["version_id"]: doc for doc in documents}
        if len(versions) != len(documents):
            raise ValueError("Повторяющиеся версии документов в корпусе")
        if len({doc["document_id"] for doc in documents}) != len(documents):
            raise ValueError("В корпусе допускается одна версия на document_id")
        chunk_ids = {chunk["chunk_id"] for chunk in chunks}
        if len(chunk_ids) != len(chunks):
            raise ValueError("Повторяющиеся идентификаторы фрагментов")
        prepared = []
        represented = set()
        for chunk in chunks:
            doc = versions.get(chunk["version_id"])
            if doc is None or chunk["document_id"] != doc["document_id"]:
                raise ValueError("Фрагмент ссылается на неизвестный документ")
            block_index = chunk["block_index"]
            start, end = chunk["start"], chunk["end"]
            if (
                not isinstance(block_index, int)
                or not 0 <= block_index < len(doc["blocks"])
                or not isinstance(start, int)
                or not isinstance(end, int)
                or not 0 <= start < end <= len(doc["blocks"][block_index]["text"])
                or doc["blocks"][block_index]["text"][start:end] != chunk["text"]
                or doc["blocks"][block_index]["locator"] != chunk["locator"]
                or doc["blocks"][block_index].get("heading_path", []) != chunk["heading_path"]
            ):
                raise ValueError("Фрагмент не совпадает с исходным блоком")
            prepared.append((chunk, _vector_literal(chunk["embedding"])))
            represented.add(chunk["version_id"])
        if represented != set(versions):
            raise ValueError("Не у каждого документа есть поисковые фрагменты")

        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(783419421)")
            conn.execute("SET LOCAL statement_timeout = '120s'")
            existing = conn.execute(
                "SELECT model_revision FROM corpus_revisions WHERE corpus_key = %s",
                (corpus_key,),
            ).fetchone()
            if existing is not None:
                doc_members = {
                    row["version_id"] for row in conn.execute(
                        "SELECT version_id FROM corpus_documents WHERE corpus_key = %s",
                        (corpus_key,),
                    )
                }
                chunk_members = {
                    row["chunk_id"] for row in conn.execute(
                        "SELECT chunk_id FROM corpus_chunks WHERE corpus_key = %s",
                        (corpus_key,),
                    )
                }
                if (
                    existing["model_revision"] != model_revision
                    or doc_members != set(versions)
                    or chunk_members != chunk_ids
                ):
                    raise ValueError("Ключ корпуса уже занят другой генерацией")

            for doc in documents:
                row = conn.execute(
                    "SELECT document_id, sha256, name, blocks, warnings "
                    "FROM document_versions WHERE version_id = %s",
                    (doc["version_id"],),
                ).fetchone()
                payload = {key: doc[key] for key in ("document_id", "sha256", "name", "blocks", "warnings")}
                if row is not None:
                    if row != payload:
                        raise ValueError("Неизменяемая версия документа уже содержит другие данные")
                else:
                    conn.execute(
                        "INSERT INTO document_versions "
                        "(version_id, document_id, sha256, name, blocks, warnings) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (doc["version_id"], doc["document_id"], doc["sha256"], doc["name"],
                         Jsonb(doc["blocks"]), Jsonb(doc["warnings"])),
                    )
            for chunk, vector in prepared:
                row = conn.execute(
                    "SELECT version_id, block_index, text, start_offset AS start, "
                    "end_offset AS end, locator, heading_path, model_revision, "
                    "coalesce(embedding_text,text) AS embedding_text "
                    "FROM chunks WHERE chunk_id = %s",
                    (chunk["chunk_id"],),
                ).fetchone()
                payload = {key: chunk[key] for key in (
                    "version_id", "block_index", "text", "start", "end", "locator", "heading_path"
                )}
                payload["model_revision"] = model_revision
                payload["embedding_text"] = chunk.get("embedding_text", chunk["text"])
                if row is not None:
                    if row != payload:
                        raise ValueError("Неизменяемый фрагмент уже содержит другие данные")
                else:
                    conn.execute(
                        "INSERT INTO chunks (chunk_id, version_id, block_index, text, "
                        "start_offset, end_offset, locator, heading_path, embedding, model_revision, embedding_text) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s)",
                        (chunk["chunk_id"], chunk["version_id"], chunk["block_index"], chunk["text"],
                         chunk["start"], chunk["end"], Jsonb(chunk["locator"]),
                         Jsonb(chunk["heading_path"]), vector, model_revision,
                         chunk.get("embedding_text", chunk["text"])),
                    )
            if existing is None:
                conn.execute(
                    "INSERT INTO corpus_revisions (corpus_key, model_revision) VALUES (%s, %s)",
                    (corpus_key, model_revision),
                )
                with conn.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO corpus_documents (corpus_key, version_id) VALUES (%s, %s)",
                        [(corpus_key, version_id) for version_id in versions],
                    )
                    cursor.executemany(
                        "INSERT INTO corpus_chunks (corpus_key, chunk_id) VALUES (%s, %s)",
                        [(corpus_key, chunk_id) for chunk_id in sorted(chunk_ids)],
                    )
            conn.execute(
                "INSERT INTO active_corpus (singleton, corpus_key) VALUES (true, %s) "
                "ON CONFLICT (singleton) DO UPDATE SET corpus_key = EXCLUDED.corpus_key",
                (corpus_key,),
            )
        return corpus_key

    def active_revision(self) -> dict[str, str]:
        with self._connect() as conn:
            active = conn.execute(
                "SELECT a.corpus_key, c.model_revision FROM active_corpus a "
                "JOIN corpus_revisions c USING (corpus_key) WHERE singleton = true"
            ).fetchone()
        if active is None:
            raise IndexUnavailableError("Индекс не опубликован: сначала выполните ingest")
        return active

    def search(
        self, query: str, vector: list[float], limit: int = 5,
        *, model_revision: str | None = None, corpus_key: str | None = None,
        mode: str = "hybrid", lexical_or: bool = False, document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 20000:
            raise ValueError("Запрос должен содержать от 1 до 20000 символов")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit должен быть целым числом от 1 до 100")
        if mode not in {"hybrid", "dense", "lexical"}:
            raise ValueError("Неизвестный режим поиска")
        if document_ids is not None and (not isinstance(document_ids, list) or len(document_ids) > 100
                                        or any(not isinstance(v, str) or not v for v in document_ids)):
            raise ValueError("Некорректный список документов для поиска")
        vector_text = _vector_literal(vector)
        with self._connect() as conn:
            conn.execute("SET LOCAL statement_timeout = '30s'")
            active = conn.execute(
                "SELECT a.corpus_key, c.model_revision FROM active_corpus a "
                "JOIN corpus_revisions c USING (corpus_key) WHERE singleton = true"
            ).fetchone()
            if active is None:
                raise IndexUnavailableError("Индекс не опубликован: сначала выполните ingest")
            if corpus_key is not None:
                active = conn.execute(
                    "SELECT corpus_key,model_revision FROM corpus_revisions WHERE corpus_key=%s",
                    (corpus_key,),
                ).fetchone()
                if active is None:
                    raise IndexUnavailableError("Запрошенная версия корпуса отсутствует")
            if model_revision is not None and active["model_revision"] != model_revision:
                raise ValueError("Версия embedding-модели не совпадает с активным индексом")
            # Explicit corpus_key keeps this request on one immutable snapshot
            # even if a concurrent publisher switches the active pointer.
            rows = conn.execute(
                """
                WITH terms AS (
                    SELECT CASE WHEN %(lexical_or)s THEN
                        replace(plainto_tsquery('russian', %(query)s)::text, ' & ', ' | ')::tsquery
                        ELSE plainto_tsquery('russian', %(query)s) END AS query,
                        tsvector_to_array(to_tsvector('russian', %(query)s)) AS lexemes
                ), selected AS MATERIALIZED (
                    SELECT c.* FROM chunks c JOIN corpus_chunks m USING (chunk_id)
                    WHERE m.corpus_key = %(corpus)s
                      AND (%(all_documents)s OR EXISTS (
                          SELECT 1 FROM document_versions d WHERE d.version_id=c.version_id
                          AND d.document_id=ANY(%(document_ids)s::text[])))
                ), dense_candidates AS (
                    SELECT chunk_id, embedding <=> %(vector)s::vector AS distance
                    FROM selected ORDER BY distance, chunk_id LIMIT %(dense_limit)s
                ), dense AS (
                    SELECT chunk_id, row_number() OVER (ORDER BY distance, chunk_id) AS rank
                    FROM dense_candidates
                ), lexical_candidates AS (
                    SELECT chunk_id,
                        CASE WHEN %(lexical_or)s THEN cardinality(ARRAY(
                            SELECT unnest(tsvector_to_array(search_text))
                            INTERSECT SELECT unnest(terms.lexemes)
                        )) ELSE 0 END AS matched_terms,
                        ts_rank_cd(search_text, terms.query) AS relevance
                    FROM selected CROSS JOIN terms
                    WHERE search_text @@ terms.query
                    ORDER BY matched_terms DESC, relevance DESC, chunk_id LIMIT %(lexical_limit)s
                ), lexical AS (
                    SELECT chunk_id, row_number() OVER (ORDER BY matched_terms DESC, relevance DESC, chunk_id) AS rank
                    FROM lexical_candidates
                ), combined AS (
                    SELECT coalesce(d.chunk_id, l.chunk_id) AS chunk_id,
                        coalesce(1.0 / (60 + d.rank), 0) + coalesce(1.0 / (60 + l.rank), 0) AS score
                    FROM dense d FULL OUTER JOIN lexical l USING (chunk_id)
                )
                SELECT c.chunk_id, d.document_id, c.version_id, d.name,
                       d.warnings AS extraction_warnings,
                       c.block_index, c.text, c.start_offset AS start, c.end_offset AS end,
                       c.locator, c.heading_path, r.score::float8 AS score,
                       (1 - (c.embedding <=> %(vector)s::vector)) AS cosine_similarity,
                       %(corpus)s::text AS corpus_revision,
                       c.model_revision
                FROM combined r JOIN selected c USING (chunk_id)
                JOIN document_versions d USING (version_id)
                ORDER BY r.score DESC, c.chunk_id LIMIT %(limit)s
                """,
                {"corpus": active["corpus_key"], "vector": vector_text, "query": query,
                 "lexical_or": lexical_or,
                 "all_documents": document_ids is None, "document_ids": document_ids or [],
                 "dense_limit": 0 if mode == "lexical" else max(20, limit * 4),
                 "lexical_limit": 0 if mode == "dense" else max(20, limit * 4), "limit": limit},
            ).fetchall()
        return rows

    def documents(self, corpus_key: str) -> list[dict]:
        """Read sources belonging to exactly one immutable corpus."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT d.document_id,d.version_id,d.sha256,d.name,d.blocks,d.warnings "
                "FROM document_versions d JOIN corpus_documents m USING(version_id) "
                "WHERE m.corpus_key=%s ORDER BY d.document_id", (corpus_key,),
            ).fetchall()

    def document(self, version_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT document_id,version_id,sha256,name,blocks,warnings "
                "FROM document_versions WHERE version_id=%s", (version_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Версия источника отсутствует")
        return row
