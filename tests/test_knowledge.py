"""Synthetic semantic map: cross-file neighbours, real source slices, honest coverage."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import time

from fastapi.testclient import TestClient
import numpy as np
import pytest

from navigator.api import create_app
from navigator.knowledge.graph import KnowledgeMap, MapBuilding, MapChanged, MapUnavailable, Snapshot
from navigator.knowledge.repository import question_key
from navigator.sources import resolve
from test_generation import fixture, generate


def corpus():
    docs = [{'document_id': name, 'version_id': letter*64, 'sha256': letter*64,
             'name': 'Синтетический файл '+name, 'blocks': [], 'warnings': []}
            for name, letter in [('A','a'), ('B','b')]]
    chunks = []
    themes = ['бронирование концертного зала', 'техническая поддержка сервера', 'командировка билеты расходы']
    for i in range(12):
        doc=docs[i%2];block_index=len(doc['blocks'])
        text=f'{themes[i//4]}: синтетическая строка {i}.'
        block={'text':text,'locator':{'block':block_index+1},'kind':'paragraph','heading_path':[],'method':'native'}
        doc['blocks'].append(block)
        vector=[0.]*384;vector[i//4]=1;vector[-1]=i*.001
        chunks.append({'chunk_id':f'c{i:02d}','document_id':doc['document_id'],'version_id':doc['version_id'],
                       'block_index':block_index,'start':0,'end':len(text),'text':text,
                       'locator':block['locator'],'heading_path':[],'embedding':vector})
    return docs,chunks


def snapshot():
    docs,chunks=corpus()
    return Snapshot({'corpus_key':'test','model_revision':'test-model'},docs,chunks)


def test_topics_mix_documents_and_neighbours_are_global_cosine():
    data=snapshot()
    assert sum(t['count'] for t in data.topics)==12
    assert any(len(t['documents'])==2 for t in data.topics)
    result=data.neighbours('c00')
    assert result['neighbours'][0]['id']=='c01'
    assert result['neighbours'][0]['document_id']=='B'
    assert result['neighbours'][0]['similarity']>.99
    assert len(result['neighbours'])==8
    docs={d['version_id']:d for d in data.documents.values()}
    store=SimpleNamespace(document=lambda version:docs[version])
    for f in [result['fragment'],*result['neighbours']]:
        ref=resolve(store,f['source_id'])
        assert f['preview']==ref['quote']
    assert data.summary()['labels_automatic'] is True
    assert 'embedding' not in data.summary()
    with pytest.raises(KeyError):data.topic('topic-999')
    with pytest.raises(KeyError):data.neighbours('unknown')


def test_topic_edges_and_question_placement_use_384d_not_layout():
    data=snapshot()
    for edge in data.edges:
        a,b=[int(edge[k].split('-')[1]) for k in ('source','target')]
        expected=float(data.centres[a]@data.centres[b])
        assert edge['similarity']==pytest.approx(expected,abs=1e-5)
    vector=data.vectors[0].tolist()
    related=data.question_topics(vector,'test-model')
    best=int(related[0]['id'].split('-')[1])
    assert related[0]['similarity']==pytest.approx(float(data.centres[best]@data.vectors[0]),abs=1e-5)
    assert data.question_topics(vector,'other-model')==[]
    assert 'result_type' not in related[0]  # Similarity never classifies coverage.


def test_empty_invalid_and_code_only_corpora():
    docs,chunks=corpus()
    with pytest.raises(MapUnavailable):Snapshot({'corpus_key':'empty'},docs,[])
    chunks[0]['embedding'][0]=float('nan')
    with pytest.raises(ValueError):Snapshot({'corpus_key':'bad'},docs,chunks)
    docs,chunks=corpus()
    for c in chunks:c['text']='123 456'
    data=Snapshot({'corpus_key':'codes','model_revision':'test-model'},docs,chunks)
    assert all(t['label'].startswith('Тема ') for t in data.topics)


def test_background_cache_and_revision_change():
    docs,chunks=corpus();active={'corpus_key':'one','model_revision':'test-model'}
    store=SimpleNamespace(active_revision=lambda:dict(active),documents=lambda key:docs,snapshot_chunks=lambda key:chunks)
    service=KnowledgeMap(store,SimpleNamespace(revision='test-model'))
    def wait():
        deadline=time.monotonic()+5
        while True:
            try:return service.snapshot()
            except MapBuilding:
                if time.monotonic()>deadline:raise AssertionError('Map build timed out')
                time.sleep(.01)
    try:
        first=wait();assert first.revision['corpus_key']=='one'
        assert service.snapshot() is first
        active['corpus_key']='two'
        with pytest.raises(MapChanged):service.snapshot('one')
        second=wait();assert second.revision['corpus_key']=='two'
        assert second is not first
    finally:service.close()


class Questions:
    def __init__(self):self.rows=[]
    def can_add(self,question):pass
    def save(self,question,answer,vector,model_revision):
        self.rows=[{'id':question_key(question),'question':question,'result':answer,
                    'corpus_key':answer['corpus_revision'],'query_vector':vector,'model_revision':model_revision,
                    'checked_at':datetime.now(timezone.utc)}]
    def list(self):return deepcopy(self.rows)


def test_public_routes_consent_checked_answers_and_stale_questions(tmp_path):
    doc,retrieved,answer=fixture();map_data=snapshot();repo=Questions()
    service=SimpleNamespace(store=SimpleNamespace(active_revision=lambda:{'corpus_key':'test'},document=lambda v:doc),
                            search=lambda *a,**kw:retrieved)
    map_service=SimpleNamespace(snapshot=lambda expected=None:map_data,
                                encode_question=lambda q:(map_data.vectors[0].tolist(),'test-model'))
    with TestClient(create_app(service=service,generator=generate(answer),knowledge_map=map_service,map_questions=repo)) as client:
        assert client.get('/map').status_code==200
        assert client.get('/assets/map.js').status_code==200
        assert client.get('/api/map').json()['chunk_count']==12
        assert client.get('/api/map/topics/topic-0?corpus_revision=test').status_code==200
        assert client.get('/api/map/fragments/c00?corpus_revision=test').json()['neighbours'][0]['document_id']=='B'
        for body in [{'question':'Когда подать?'},{'question':'Когда подать?','public_data':False},
                     {'question':' ','public_data':True},{'question':'a'*501,'public_data':True}]:
            assert client.post('/api/map/questions',json=body).status_code==422
        assert not repo.rows
        result=client.post('/api/map/questions',json={'question':'Когда подать?','public_data':True})
        assert result.status_code==201 and result.json()['answer']['result_type']=='answered'
        public=client.get('/api/map').json()['questions'][0]
        assert not public['stale'] and public['related_topics']
        assert 'query_vector' not in public and 'model_revision' not in public
        repo.rows[0]['corpus_key']='older'
        assert client.get('/api/map').json()['questions'][0]['stale'] is True


def test_technical_model_failure_does_not_create_gap():
    doc,retrieved,answer=fixture();repo=Questions()
    service=SimpleNamespace(store=SimpleNamespace(active_revision=lambda:{'corpus_key':'test'}),search=lambda *a,**kw:retrieved)
    maps=SimpleNamespace(encode_question=lambda q:([1.]*384,'test-model'))
    with TestClient(create_app(service=service,generator=generate(answer,status=401),knowledge_map=maps,map_questions=repo)) as client:
        assert client.post('/api/map/questions',json={'question':'Когда подать?','public_data':True}).status_code==502
        assert repo.rows==[]


def test_question_key_deduplicates_case_and_whitespace():
    assert question_key(' Как  оформить ОТПУСК? ')==question_key('как оформить отпуск?')
