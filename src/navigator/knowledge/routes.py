"""The map is public just like the demo; sharing a checked question is explicit."""
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .graph import MapBuilding, MapChanged, MapUnavailable
from .repository import QuestionLimit


class SharedQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1, max_length=500)
    public_data: Literal[True]

    @field_validator('question')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Введите вопрос')
        return value.strip()


def install_routes(app, answer):
    def service(request):
        value = request.app.state.knowledge_map
        if value is None:
            raise HTTPException(503, 'Карта знаний не настроена.')
        return value

    @app.exception_handler(MapBuilding)
    def building(request, exc):
        return JSONResponse({'status': 'building', 'detail': str(exc)}, status_code=202)

    @app.exception_handler(MapChanged)
    def changed(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.exception_handler(MapUnavailable)
    def unavailable(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=503)

    @app.exception_handler(QuestionLimit)
    def limit(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=429)

    @app.get('/map', include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).parents[1] / 'static' / 'map.html')

    @app.get('/api/map')
    def graph(request: Request, include_questions: bool = True):
        snapshot = service(request).snapshot()
        questions = []
        for row in (request.app.state.map_questions.list() if include_questions else []):
            vector = row.pop('query_vector')
            model_revision = row.pop('model_revision')
            questions.append({**row, 'stale': row['corpus_key'] != snapshot.revision['corpus_key'],
                              'related_topics': snapshot.question_topics(vector, model_revision)})
        return {**snapshot.summary(), 'questions': questions}

    @app.get('/api/map/topics/{topic_id}')
    def topic(topic_id: str, request: Request, corpus_revision: str):
        try:
            return service(request).snapshot(corpus_revision).topic(topic_id)
        except KeyError:
            raise HTTPException(404, 'Тема не найдена.') from None

    @app.get('/api/map/fragments/{chunk_id}')
    def fragment(chunk_id: str, request: Request, corpus_revision: str):
        try:
            return service(request).snapshot(corpus_revision).neighbours(chunk_id)
        except KeyError:
            raise HTTPException(404, 'Фрагмент не найден.') from None

    @app.post('/api/map/questions', status_code=201)
    def check(body: SharedQuestion, request: Request):
        graph_service = service(request)
        repo = request.app.state.map_questions
        repo.can_add(body.question)
        result = answer(body.question, request)
        vector, revision = graph_service.encode_question(body.question)
        repo.save(body.question, result, vector, revision)
        return {'question': body.question, 'answer': result, 'shared': True}
