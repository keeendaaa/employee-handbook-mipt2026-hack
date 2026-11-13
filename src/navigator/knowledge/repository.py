"""Only explicitly shared, checked questions; technical failures never become gaps."""
import hashlib

from psycopg.types.json import Jsonb


class QuestionLimit(RuntimeError):
    pass


def question_key(question):
    return hashlib.sha256(' '.join(question.casefold().split()).encode()).hexdigest()


class QuestionRepository:
    def __init__(self, store):
        self.store = store

    def can_add(self, question):
        key = question_key(question)
        with self.store._connect() as conn:
            row = conn.execute('SELECT count(DISTINCT question_hash) AS count FROM map_questions').fetchone()
            known = conn.execute('SELECT 1 FROM map_questions WHERE question_hash=%s LIMIT 1', (key,)).fetchone()
        if row['count'] >= 500 and not known:
            raise QuestionLimit('На общей карте достигнут лимит 500 вопросов.')

    def save(self, question, answer, vector, model_revision):
        # Persist only the validated public answer fields, never API credentials or provider metadata.
        if answer['result_type'] not in {'answered', 'partial', 'not_found', 'needs_clarification', 'conflict'}:
            raise ValueError('Техническую ошибку нельзя сохранять как пробел')
        payload = {key: answer[key] for key in ('result_type', 'summary', 'steps', 'citations',
                   'missing_information', 'clarifications', 'conflicts')}
        with self.store._connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(783419423)')
            self.can_add(question)
            conn.execute('''INSERT INTO map_questions(question_hash,corpus_key,question,result,query_vector,model_revision)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(question_hash,corpus_key) DO UPDATE
                SET result=excluded.result,query_vector=excluded.query_vector,model_revision=excluded.model_revision,
                    checked_at=now()''',
                (question_key(question), answer['corpus_revision'], question, Jsonb(payload), Jsonb(vector), model_revision))

    def list(self):
        with self.store._connect() as conn:
            return conn.execute('''SELECT DISTINCT ON(question_hash) question_hash AS id,corpus_key,question,result,
                query_vector,model_revision,checked_at FROM map_questions
                ORDER BY question_hash,checked_at DESC''').fetchall()
