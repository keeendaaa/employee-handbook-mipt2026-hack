CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_versions (
    version_id text PRIMARY KEY,
    document_id text NOT NULL,
    sha256 text NOT NULL,
    name text NOT NULL,
    blocks jsonb NOT NULL,
    warnings jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id text PRIMARY KEY,
    version_id text NOT NULL REFERENCES document_versions(version_id),
    block_index integer NOT NULL CHECK (block_index >= 0),
    text text NOT NULL CHECK (length(text) > 0),
    start_offset integer NOT NULL CHECK (start_offset >= 0),
    end_offset integer NOT NULL CHECK (end_offset > start_offset),
    locator jsonb NOT NULL,
    heading_path jsonb NOT NULL,
    embedding vector(384) NOT NULL,
    model_revision text NOT NULL,
    search_text tsvector GENERATED ALWAYS AS (to_tsvector('russian'::regconfig, text)) STORED,
    CHECK (char_length(text) = end_offset - start_offset)
);
CREATE INDEX IF NOT EXISTS chunks_search_text_idx ON chunks USING gin(search_text);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_text text;

CREATE TABLE IF NOT EXISTS corpus_revisions (
    corpus_key text PRIMARY KEY,
    model_revision text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS corpus_documents (
    corpus_key text NOT NULL REFERENCES corpus_revisions(corpus_key),
    version_id text NOT NULL REFERENCES document_versions(version_id),
    PRIMARY KEY (corpus_key, version_id)
);
CREATE TABLE IF NOT EXISTS corpus_chunks (
    corpus_key text NOT NULL REFERENCES corpus_revisions(corpus_key),
    chunk_id text NOT NULL REFERENCES chunks(chunk_id),
    PRIMARY KEY (corpus_key, chunk_id)
);
CREATE TABLE IF NOT EXISTS active_corpus (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    corpus_key text NOT NULL REFERENCES corpus_revisions(corpus_key)
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id uuid PRIMARY KEY,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','downloading','extracting','indexing','ready','partial','failed')),
    filename text,
    source_url text,
    replace_existing boolean NOT NULL DEFAULT false,
    attempts integer NOT NULL DEFAULT 0,
    lease_until timestamptz,
    owner uuid,
    message text NOT NULL DEFAULT 'Ожидание обработки',
    warnings jsonb NOT NULL DEFAULT '[]',
    corpus_key text,
    document_id text,
    duplicate boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS import_worker_heartbeat (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    touched_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS map_questions (
    question_hash text NOT NULL,
    corpus_key text NOT NULL REFERENCES corpus_revisions(corpus_key),
    question text NOT NULL CHECK (char_length(question) BETWEEN 1 AND 500),
    result jsonb NOT NULL,
    query_vector jsonb NOT NULL,
    model_revision text NOT NULL,
    checked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (question_hash, corpus_key)
);
