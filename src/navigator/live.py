"""Request-local SSE progress. Emits observable pipeline events, never model reasoning."""
import asyncio
import json
from queue import Empty, Full, Queue
import threading

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import psycopg

from .generation import GenerationError, evidence
from .ingest.storage import IndexUnavailableError
from .knowledge.graph import MapBuilding, MapChanged, MapUnavailable


class QueryCancelled(RuntimeError):
    pass


def retrieval_trace(retrieved, knowledge_map, *, include_context=True):
    """All displayed sources come from this exact retrieval and LLM evidence budget."""
    snapshot = None
    state = 'unavailable'
    if knowledge_map is not None:
        try:
            snapshot = knowledge_map.snapshot(retrieved['corpus_revision'])
            state = 'ready'
        except MapBuilding:
            state = 'building'
        except MapChanged:
            state = 'stale'
        except (MapUnavailable, IndexUnavailableError, psycopg.Error, ValueError):
            state = 'unavailable'
    candidates = {}
    for rank, row in enumerate(retrieved['results'], 1):
        ref = row['citation']
        candidates.setdefault(ref['source_id'], {'citation': ref, 'rank': rank, 'role': 'found', 'included': False})
    supplied = evidence(retrieved) if include_context else []
    for ref in supplied:
        item = candidates.setdefault(ref['source_id'], {'citation': ref, 'rank': None, 'role': 'context'})
        item['included'] = True
    mapping = {}
    if snapshot is not None:
        for i, chunk in enumerate(snapshot.chunks):
            mapping.setdefault((chunk['version_id'], chunk['block_index']), []).append(
                (chunk['start'], chunk['end'], f'topic-{snapshot.chunk_topics[i]}'))
    for item in candidates.values():
        ref = item['citation']
        item['topic_ids'] = sorted({topic for start, end, topic in mapping.get((ref['version_id'], ref['block_index']), [])
                                    if start < ref['end'] and end > ref['start']})
    used_topics = {t for item in candidates.values() for t in item['topic_ids']}
    return {'corpus_revision': retrieved['corpus_revision'], 'map_status': state,
            'sources': list(candidates.values()), 'evidence_source_ids': [r['source_id'] for r in supplied],
            'topics': [t for t in snapshot.topics if t['id'] in used_topics] if snapshot is not None else [],
            'retrieved_count': len(retrieved['results'])}


def stream_response(run):
    queue = Queue(maxsize=96)
    stopped = threading.Event()
    sentinel = object()

    def emit(event):
        while not stopped.is_set():
            try:
                queue.put(event, timeout=.2)
                return
            except Full:
                continue
        raise QueryCancelled()

    def produce():
        try:
            run(emit)
            emit({'type': 'done'})
        except QueryCancelled:
            pass
        except Exception as exc:
            if not stopped.is_set():
                if isinstance(exc, HTTPException):
                    code, detail = exc.status_code, exc.detail
                elif isinstance(exc, GenerationError):
                    code, detail = 502, str(exc)
                elif isinstance(exc, (IndexUnavailableError, psycopg.Error)):
                    code, detail = 503, 'Индекс или база данных недоступны. Повторите позже.'
                elif isinstance(exc, ValueError):
                    code, detail = 400, 'Не удалось обработать вопрос. Проверьте формулировку и параметры.'
                else:
                    code, detail = 500, 'Техническая ошибка запроса. Повторите позже.'
                try:
                    emit({'type': 'error', 'status_code': code, 'detail': detail})
                except QueryCancelled:
                    pass
        finally:
            while not stopped.is_set():
                try:
                    queue.put(sentinel, timeout=.2)
                    break
                except Full:
                    continue

    async def events():
        task = asyncio.create_task(asyncio.to_thread(produce))
        last_ping = asyncio.get_running_loop().time()
        try:
            while True:
                try:
                    item = await asyncio.to_thread(queue.get, True, .25)
                except Empty:
                    now = asyncio.get_running_loop().time()
                    if now-last_ping >= 10:
                        yield ': keepalive\n\n'
                        last_ping = now
                    continue
                if item is sentinel:
                    break
                yield 'data: ' + json.dumps(item, ensure_ascii=False, allow_nan=False) + '\n\n'
        finally:
            stopped.set()
            # A synchronous provider call already in flight may finish in its thread.
            task.cancel()

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
