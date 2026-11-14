"""Isolated UI contract server with explicitly synthetic data; never production.

Uses the real FastAPI routes, SSE framing, source resolver, imports and feedback.
Only retrieval, generation, import worker, map and upstream mail are test doubles.
"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'src'))
from navigator.api import create_app
from navigator.generation import GenerationError
from navigator.sources import reference
import uvicorn

TEXT = 'СИНТЕТИЧЕСКИЙ МАТЕРИАЛ ДЛЯ ПРОВЕРКИ UI.\n1. Проверьте тестовый доступ.\n2. Подготовьте тестовый кабинет.\n3. Прочитайте тестовую инструкцию.\n4. Отправьте тестовую заявку.\nКонец тестового материала.'
DOC = {'version_id':'a'*64,'document_id':'b'*64,'name':'Синтетический регламент — E2E',
       'sha256':'c'*64,'warnings':[], 'blocks':[{'text':TEXT,'locator':{'page':1},'method':'native'}]}
STEPS = ['Проверьте тестовый доступ.','Подготовьте тестовый кабинет.',
         'Прочитайте тестовую инструкцию.','Отправьте тестовую заявку.']
REFS = [reference(DOC,0,TEXT.index(s),TEXT.index(s)+len(s)) for s in STEPS]


def answer(question):
    missing = 'Неизвестный вопрос' in question
    return {'result_type':'not_found' if missing else 'answered',
      'summary':[] if missing else [{'text':'Порядок действий из синтетического тестового материала.','citation_ids':[REFS[0]['source_id']]}],
      'steps':[] if missing else [{'text':s,'citation_ids':[r['source_id']]} for s,r in zip(STEPS,REFS)],
      'citations':[] if missing else deepcopy(REFS),'missing_information':['В тестовой базе ответ не найден.'] if missing else [],
      'clarifications':[],'conflicts':[],'corpus_revision':'synthetic-e2e','limitations':[]}


class Generator:
    def answer(self, question, retrieved, progress=None):
        if 'Технический сбой' in question:
            raise GenerationError('Синтетический технический сбой. Повторите запрос.')
        if progress:
            progress({'type':'stage','stage':'generation'})
        if 'Медленная' in question:
            import time
            time.sleep(.5)
        return answer(question)


class Snapshot:
    revision = {'corpus_key':'synthetic-e2e'}
    chunks = []
    topics = [{'id':'topic-0','label':'Тестовая процедура','count':4,'documents':[{'id':'b'*64,'count':4}]}]
    def summary(self):
        return {'status':'ready','corpus_revision':'synthetic-e2e','chunk_count':4,
                'documents':[{'id':'b'*64,'name':DOC['name']}], 'topics':self.topics,'edges':[]}
    def topic(self, _id):
        return {**self.topics[0],'fragments':[{'id':str(i),'document_name':DOC['name'],'source_id':r['source_id'],'preview':r['quote']} for i,r in enumerate(REFS)]}
    def question_topics(self, vector, revision):
        return [{'id':'topic-0','similarity':.9}]


class Questions:
    rows = [{'id':'synthetic-question','corpus_key':'synthetic-e2e','question':'Неизвестный вопрос',
             'result':answer('Неизвестный вопрос'),'query_vector':[1],'model_revision':'synthetic',
             'checked_at':'2026-11-14T00:00:00Z'}]
    def list(self):
        return deepcopy(self.rows)
    def can_add(self, question):
        pass
    def save(self, question, result, vector, revision):
        self.rows = [{'id':'synthetic-question','corpus_key':'synthetic-e2e','question':question,
          'result':result,'query_vector':[1],'model_revision':'synthetic','checked_at':'2026-11-14T00:00:00Z'}]


class Imports:
    def __init__(self):
        self.jobs = {}
    def online(self):
        return True
    def create(self, job_id=None, filename=None, **kw):
        key = str(job_id or uuid4())
        self.jobs[key] = {'id':key,'status':'queued','filename':filename or 'synthetic.pdf',
          'message':'Синтетическая очередь для проверки интерфейса.','warnings':[],
          'duplicate':False,'worker_available':True,'polls':0}
        return key
    def get(self, job_id):
        job = self.jobs[str(job_id)]
        job['polls'] += 1
        if job['polls'] > 1:
            job.update(status='ready', message='Синтетический импорт завершён.')
        return {k:v for k,v in job.items() if k!='polls'}


MAIL = {'mailbox':'synthetic@example.org','settings':{'enabled':True,'reply_without_issue':False,'senders':[],'api_url':'https://example.org/api/mail/analyze'},
        'worker':{'state':'online','detail':'Синтетический почтовый сервис'},
        'events':[{'sender':'test@example.org','subject':'Синтетическое письмо','status':'uncertain',
                   'detail':'Доставка не подтверждена','updated':'2026-11-14T00:00:00Z'}]}


class MailPanel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def send(self, body):
        raw = json.dumps(body).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        assert self.headers['Host']=='127.0.0.1:8787'
        self.send(MAIL)
    def do_POST(self):
        assert self.headers['Origin']=='http://127.0.0.1:8787'
        MAIL['settings'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        MAIL['worker']['state'] = 'online' if MAIL['settings']['enabled'] else 'paused'
        self.send(MAIL['settings'])


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='smena-ui-contract-') as folder:
        os.environ['MATERIAL_REQUEST_DB'] = str(Path(folder)/'requests.sqlite')
        from navigator.admin_auth import password_hash
        credentials = Path(folder) / 'admin.hash'
        credentials.write_text(password_hash('synthetic-e2e-password'))
        os.environ['ADMIN_TEST_USERNAME'] = 'synthetic-admin'
        os.environ['ADMIN_TEST_PASSWORD_HASH_FILE'] = str(credentials)
        panel = ThreadingHTTPServer(('127.0.0.1',0),MailPanel)
        os.environ['MAILBOT_PANEL_URL'] = f'http://127.0.0.1:{panel.server_port}'
        threading.Thread(target=panel.serve_forever,daemon=True).start()
        service = SimpleNamespace(store=SimpleNamespace(active_revision=lambda:{'corpus_key':'synthetic-e2e'},document=lambda v:DOC,document_in_corpus=lambda d,c:DOC if d==DOC['document_id'] else None),
          search=lambda q,**kw:{'corpus_revision':'synthetic-e2e','results':[{'citation':r,'context_sources':[]} for r in REFS]})
        graph = SimpleNamespace(snapshot=lambda *args:Snapshot(),encode_question=lambda q:([1],'synthetic'),close=lambda:None)
        app = create_app(service=service,generator=Generator(),knowledge_map=graph,map_questions=Questions(),
             import_repository=Imports(),import_directory=Path(folder)/'imports',frontend_directory=ROOT/'frontend/dist')
        uvicorn.run(app,host='127.0.0.1',port=8008,access_log=False)
