"""Real SSE framing with synthetic evidence; no provider/network calls."""
import asyncio
import json
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from navigator.api import create_app
from navigator.knowledge.graph import MapChanged
from navigator.live import retrieval_trace, stream_response
from test_generation import fixture, generate


def events(response):
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]


def app_for(answer=None, status=200, knowledge_map=None):
    doc,retrieved,default=fixture()
    def search(question, **kwargs):
        progress=kwargs.get('progress')
        if progress:
            progress({'type':'stage','stage':'embedding','status':'complete'})
            progress({'type':'stage','stage':'retrieval','part':1,'parts':1})
        return retrieved
    service=SimpleNamespace(store=SimpleNamespace(active_revision=lambda:{'corpus_key':'test'},document=lambda v:doc),search=search)
    return create_app(service=service,generator=generate(answer or default,status=status),knowledge_map=knowledge_map)


def test_stream_retrieval_precedes_generation_and_preserves_exact_sources():
    with TestClient(app_for()) as client:
        response=client.post('/api/query/stream',json={'question':'Когда подать?'})
        assert response.headers['content-type'].startswith('text/event-stream')
        assert response.headers['cache-control']=='no-store'
        frames=events(response);types=[e['type'] for e in frames]
        assert types[0]=='started' and types[-1]=='done'
        retrieval=next(e for e in frames if e['type']=='retrieval')
        final=next(e for e in frames if e['type']=='answer')['answer']
        generation=next(i for i,e in enumerate(frames) if e.get('stage')=='generation')
        assert types.index('retrieval')<generation<types.index('answer')
        ids={s['citation']['source_id'] for s in retrieval['trace']['sources']}
        assert set(c['source_id'] for c in final['citations'])<=ids
        assert all(s['topic_ids']==[] for s in retrieval['trace']['sources'])
        assert client.post('/api/ask',json={'question':'Когда подать?'}).status_code==200


def test_search_only_has_no_model_evidence_and_no_answer_classification():
    with TestClient(app_for(status=401)) as client:
        response=client.post('/api/query/stream',json={'question':'Когда подать?','mode':'search'})
        frames=events(response)
        trace=next(e for e in frames if e['type']=='retrieval')['trace']
        assert trace['evidence_source_ids']==[]
        assert all(not s['included'] for s in trace['sources'])
        assert frames[-1]['type']=='done'
        assert any(e['type']=='search_complete' for e in frames)
        assert not any(e.get('stage')=='generation' or e['type'] in ('answer','error') for e in frames)


def test_provider_error_keeps_retrieval_and_never_creates_false_not_found():
    with TestClient(app_for(status=401)) as client:
        frames=events(client.post('/api/query/stream',json={'question':'Когда подать?'}))
        assert any(e['type']=='retrieval' for e in frames)
        assert frames[-1]['type']=='error' and frames[-1]['status_code']==502
        assert not any(e['type'] in ('answer','done') for e in frames)


def test_stale_map_is_optional_for_valid_query():
    def stale(*a,**kw):raise MapChanged('База обновилась')
    maps=SimpleNamespace(snapshot=stale)
    with TestClient(app_for(knowledge_map=maps)) as client:
        frames=events(client.post('/api/query/stream',json={'question':'Когда подать?'}))
        assert next(e for e in frames if e['type']=='retrieval')['trace']['map_status']=='stale'
        assert next(e for e in frames if e['type']=='answer')['answer']['result_type']=='answered'


def test_stream_and_legacy_ask_share_rate_limit():
    with TestClient(app_for()) as client:
        for _ in range(15):
            assert client.post('/api/ask',json={'question':'Когда подать?'}).status_code==200
        frames=events(client.post('/api/query/stream',json={'question':'Когда подать?'}))
        assert frames[-1]['type']=='error' and frames[-1]['status_code']==429
        assert events(client.post('/api/query/stream',json={'question':'Когда подать?','mode':'search'}))[-1]['type']=='done'


def test_disconnect_before_model_prevents_later_generation():
    gate,finished=threading.Event(),threading.Event();calls=[]
    def run(emit):
        try:
            emit({'type':'started'});gate.wait(2)
            emit({'type':'stage','stage':'generation'});calls.append('model')
        finally:finished.set()
    response=stream_response(run)
    async def consume():
        iterator=response.body_iterator
        assert 'started' in await anext(iterator)
        await iterator.aclose();gate.set()
        assert await asyncio.to_thread(finished.wait,2)
    asyncio.run(consume())
    assert calls==[]


@pytest.mark.parametrize('body',[{'question':' '},{'question':'x','mode':'invalid'},{'question':'x','limit':True}])
def test_stream_validation_matches_existing_query_contract(body):
    with TestClient(app_for()) as client:
        assert client.post('/api/query/stream',json=body).status_code==422


@pytest.mark.parametrize('later', ['ready', 'stale', 'error'])
def test_cold_map_enrichment_uses_same_retrieval_and_never_repeats_model(later):
    from navigator.knowledge.graph import MapBuilding
    _, retrieved, _ = fixture()
    ref = retrieved['results'][0]['citation']
    calls = []
    def snapshot(expected):
        calls.append(expected)
        if len(calls) == 1:
            raise MapBuilding('Building')
        if later == 'stale':
            raise MapChanged('Changed')
        if later == 'error':
            raise RuntimeError('Optional map failure')
        return SimpleNamespace(chunks=[{'version_id': ref['version_id'], 'block_index': ref['block_index'],
                                       'start': ref['start'], 'end': ref['end']}],
                               chunk_topics={0: 0}, topics=[{'id': 'topic-0'}])
    app = app_for(knowledge_map=SimpleNamespace(snapshot=snapshot))
    with TestClient(app) as client:
        search = app.state.service.search
        answer = app.state.generator.answer
        searches, generations = [], []
        def counted_search(*a, **kw):
            searches.append(1)
            return search(*a, **kw)
        def counted_answer(*a, **kw):
            generations.append(1)
            return answer(*a, **kw)
        app.state.service.search = counted_search
        app.state.generator.answer = counted_answer
        frames = events(client.post('/api/query/stream', json={'question': 'Когда подать?'}))
        types = [e['type'] for e in frames]
        initial = next(e['trace'] for e in frames if e['type'] == 'retrieval')
        assert initial['map_status'] == 'building'
        assert searches == generations == [1]
        assert calls == ['test', 'test']
        assert types[-1] == 'done' and 'answer' in types
        if later == 'ready':
            updated = next(e['trace'] for e in frames if e['type'] == 'map_update')
            assert types.index('retrieval') < types.index('map_update') < types.index('answer')
            assert updated['corpus_revision'] == initial['corpus_revision']
            assert updated['evidence_source_ids'] == initial['evidence_source_ids']
            assert updated['sources'][0]['topic_ids'] == ['topic-0']
        else:
            assert 'map_update' not in types
