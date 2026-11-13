"""Persistent shared import queue, bounded and recoverable after worker restart."""

from uuid import uuid4
from psycopg.types.json import Jsonb

from .download import ImportFailure

TERMINAL = {'ready', 'partial', 'failed'}


class ImportRepository:
    def __init__(self, store):
        self.store = store

    def online(self):
        with self.store._connect() as conn:
            row = conn.execute("SELECT touched_at > now()-interval '45 seconds' AS online FROM import_worker_heartbeat WHERE singleton=true").fetchone()
        return bool(row and row['online'])

    def heartbeat(self, job_id=None, owner=None):
        with self.store._connect() as conn:
            conn.execute("INSERT INTO import_worker_heartbeat(singleton,touched_at) VALUES(true,now()) ON CONFLICT(singleton) DO UPDATE SET touched_at=now()")
            if job_id:
                conn.execute("UPDATE import_jobs SET lease_until=now()+interval '90 seconds',updated_at=now() WHERE id=%s AND owner=%s AND status NOT IN ('ready','partial','failed')", (job_id, owner))

    def create(self, *, job_id=None, filename=None, source_url=None, replace_existing=False):
        job_id = job_id or uuid4()
        with self.store._connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(783419422)')
            count = conn.execute("SELECT count(*) FILTER (WHERE status NOT IN ('ready','partial','failed')) AS pending,count(*) FILTER (WHERE created_at>now()-interval '24 hours') AS daily FROM import_jobs").fetchone()
            if count['pending'] >= 5 or count['daily'] >= 40:
                raise ImportFailure('Очередь импорта заполнена или исчерпан дневной лимит демонстрации. Повторите позже.')
            conn.execute("INSERT INTO import_jobs(id,filename,source_url,replace_existing) VALUES(%s,%s,%s,%s)", (job_id, filename, source_url, replace_existing))
        return str(job_id)

    def get(self, job_id):
        with self.store._connect() as conn:
            row = conn.execute("SELECT id,status,filename,message,warnings,corpus_key,document_id,duplicate,created_at,updated_at FROM import_jobs WHERE id=%s", (job_id,)).fetchone()
        if row is None:
            raise KeyError('Import job absent')
        row['id'] = str(row['id'])
        row['worker_available'] = self.online() if row['status'] not in TERMINAL else True
        return row

    def claim(self):
        owner = uuid4()
        with self.store._connect() as conn:
            row = conn.execute("SELECT * FROM import_jobs WHERE status='queued' OR (status NOT IN ('ready','partial','failed') AND lease_until<now()) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if row is None:
                return None
            if row['attempts'] >= 3:
                conn.execute("UPDATE import_jobs SET status='failed',source_url=NULL,message='Обработка была прервана несколько раз. Попробуйте меньший файл.',updated_at=now() WHERE id=%s", (row['id'],))
                return None
            conn.execute("UPDATE import_jobs SET status='extracting',owner=%s,attempts=attempts+1,lease_until=now()+interval '90 seconds',updated_at=now() WHERE id=%s", (owner, row['id']))
        row['owner'] = owner
        return row

    def update(self, job, status, message, *, filename=None, warnings=None, corpus_key=None, document_id=None, duplicate=False):
        with self.store._connect() as conn:
            result = conn.execute("UPDATE import_jobs SET status=%s,message=%s,filename=coalesce(%s,filename),warnings=%s,corpus_key=%s,document_id=%s,duplicate=%s,source_url=CASE WHEN %s THEN NULL ELSE source_url END,updated_at=now() WHERE id=%s AND owner=%s RETURNING id",
                (status,message,filename,Jsonb(warnings or []),corpus_key,document_id,duplicate,status in TERMINAL,job['id'],job['owner'])).fetchone()
        if result is None:
            raise ImportFailure('Обработка передана другому обработчику. Дождитесь обновления статуса.')
