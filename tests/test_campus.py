"""User-supplied place names must not become invented rules or forced meanings."""

from types import SimpleNamespace

import pytest

from navigator.campus import expand_campus_names
from navigator.retrieval import RetrievalService
from test_retrieval import Tokenizer


@pytest.mark.parametrize('query,expected', [
    ('Как попасть в НК?', 'Как попасть в новый корпус?'),
    ('Пропуск в кпм', 'Пропуск в корпус прикладной математики'),
    ('Где вход в ГК?', 'Где вход в главный корпус?'),
    ('Как получить пропуск в Цифру?', 'Как получить пропуск в Физтех Цифра?'),
    ('Кабинет в цифре', 'Кабинет в Физтех Цифра'),
])
def test_expands_supplied_place_names(query, expected):
    expanded, hints = expand_campus_names(query)
    assert expanded == expected
    assert hints and all(h['source'] == 'user_glossary' for h in hints)


@pytest.mark.parametrize('query', [
    'Какая последняя цифра номера ФЛС?', 'Что означает цифра в смете?',
    'Какой номер кабинета?', 'НК РФ и ГК РФ', 'Какие документы нужны в Физтех Цифра?',
    'Как оформить заявку в экономический отдел?', 'НКВД и ГКНТ',
])
def test_does_not_expand_common_digits_codes_full_names_or_substrings(query):
    assert expand_campus_names(query) == (query, [])


def test_arktika_is_a_name_hint_without_invented_location():
    query = 'Как пройти в Арктику?'
    expanded, hints = expand_campus_names(query)
    assert expanded == query
    assert hints == [{'alias': 'Арктику', 'name': 'Арктика', 'source': 'user_glossary'}]


def test_retrieval_keeps_original_query_and_canonical_source_and_coverage():
    queries = []
    documents = []
    for index, text in enumerate(['Синтетический текст без нужного здания.', 'Синтетическая запись: новый корпус.']):
        block = {'text': text, 'locator': {'block': 1}, 'kind': 'paragraph', 'heading_path': [], 'method': 'native'}
        documents.append({'document_id': str(index), 'version_id': str(index + 1) * 64, 'sha256': 'f' * 64,
                          'name': 'Синтетический документ ' + str(index), 'blocks': [block], 'warnings': []})
    def search(query, vector, **kwargs):
        queries.append(query)
        assert kwargs['corpus_key'] == 'snapshot'
        doc = documents[1 if 'новый корпус' in query else 0]
        block = doc['blocks'][0]
        return [{'document_id': doc['document_id'], 'version_id': doc['version_id'], 'chunk_id': doc['document_id'],
                 'text': block['text'], 'block_index': 0, 'start': 0, 'end': len(block['text']),
                 'locator': block['locator'], 'heading_path': []}]
    store = SimpleNamespace(active_revision=lambda: {'corpus_key': 'snapshot', 'model_revision': 'test'},
                            documents=lambda key: documents, search=search)
    embedder = SimpleNamespace(tokenizer=Tokenizer(), revision='test', encode=lambda texts, **kw: [[1.] * 384 for _ in texts])
    result = RetrievalService(store, embedder).search('Пропуск в НК?', limit=2)
    assert queries == ['Пропуск в НК?', 'Пропуск в новый корпус?']
    assert result['query_parts'] == ['Пропуск в НК?']
    assert result['unrepresented_query_parts'] == []
    assert result['results'][0]['document_id'] == '1'
    assert result['results'][0]['citation']['quote'] == 'Синтетическая запись: новый корпус.'
    assert result['results'][0]['matched_query_parts'] == [0]
