"""Snapshot-pinned, local semantic topics and exact global cosine neighbours."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import math
import threading
import time

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from threadpoolctl import threadpool_limits

from ..sources import reference

STOP = set('''это этого этой этих при для или как что так все всех его ее ещё если без был быть были будет будут быть вам вас ваш ваши где да до его ему есть же за из их либо между может могут надо над нам нас наш наши нее ней них но она они оно под после потому почему про раз разный сам со так также такой там те тем то того тоже только том тот тут ты уже чем через чтобы этот эта эти января февраля марта апреля мая июня июля августа сентября октября ноября декабря года году лет дней день время случае случаях соответствии настоящий настоящего настоящим настоящей настоящие настоящих положение положения положением порядке порядок пункт пункта пунктом пункты раздел раздела приложение приложения мфти университета университет федеральное государственное образовательное учреждение высшего образования национальный исследовательский московский физико технический институт документ документа документы имени фамилия подпись дата далее должный должна должен должны основании осуществлять осуществляется осуществления является являются том числе'''.split())


class MapBuilding(RuntimeError):
    pass


class MapUnavailable(RuntimeError):
    pass


class MapChanged(RuntimeError):
    pass


def unit_matrix(values):
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != 384 or not np.isfinite(matrix).all():
        raise ValueError('Некорректные векторы карты')
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norm == 0).any():
        raise ValueError('Нулевой вектор карты')
    return matrix / norm


class Snapshot:
    def __init__(self, revision, documents, chunks):
        if not chunks or len(chunks) > 20000:
            raise MapUnavailable('Карта поддерживает от 1 до 20 000 фрагментов; поиск остаётся доступен.')
        self.revision = revision
        self.documents = {d['version_id']: d for d in documents}
        self.chunks = [{k: v for k, v in c.items() if k not in ('embedding', 'embedding_text')} for c in chunks]
        self.vectors = unit_matrix([c['embedding'] for c in chunks])
        self.indices = {c['chunk_id']: i for i, c in enumerate(chunks)}
        count = min(32, max(1, round(math.sqrt(len(chunks)))))
        with threadpool_limits(limits=1):
            if count == 1:
                labels = np.zeros(len(chunks), dtype=int)
            else:
                labels = MiniBatchKMeans(n_clusters=count, random_state=42, n_init=3,
                                        batch_size=512, max_iter=60).fit_predict(self.vectors)
        # IDs are local to this immutable revision; empty clusters are omitted.
        self.members = [np.flatnonzero(labels == label) for label in sorted(set(labels))]
        self.centres = unit_matrix([self.vectors[indices].mean(axis=0) for indices in self.members])
        texts = [' '.join(self.chunks[int(i)]['text'] for i in indices)[:250000] for indices in self.members]
        names = []
        try:
            tfidf = TfidfVectorizer(max_features=5000, stop_words=sorted(STOP),
                                   token_pattern=r'(?u)\b[а-яёa-z][а-яёa-z-]{3,}\b')
            weights = tfidf.fit_transform(texts).toarray()
            terms = tfidf.get_feature_names_out()
            for row in weights:
                names.append([str(terms[i]) for i in np.argsort(-row, kind='stable')[:3] if row[i] > 0])
        except ValueError:
            # A corpus of only codes/numbers has no lexical labels; vectors remain usable.
            names = [[] for _ in self.members]
        self.topics = []
        self.chunk_topics = {}
        for i, indices in enumerate(self.members):
            docs = Counter(self.chunks[int(index)]['document_id'] for index in indices)
            self.topics.append({'id': f'topic-{i}', 'label': ' · '.join(names[i]) or f'Тема {i+1}',
                                'keywords': names[i], 'count': len(indices),
                                'documents': [{'id': key, 'count': value} for key, value in docs.most_common()]})
            self.chunk_topics.update({int(index): i for index in indices})
        similarities = self.centres @ self.centres.T
        edges = {}
        for i in range(len(self.topics)):
            others = [int(j) for j in np.argsort(-similarities[i], kind='stable') if j != i][:3]
            for j in others:
                a, b = sorted((i, j))
                edges[(a, b)] = {'source': f'topic-{a}', 'target': f'topic-{b}',
                                 'similarity': round(float(similarities[a, b]), 5), 'kind': 'similarity'}
        self.edges = list(edges.values())

    def summary(self):
        return {'status': 'ready', 'corpus_revision': self.revision['corpus_key'],
                'model_revision': self.revision['model_revision'], 'chunk_count': len(self.chunks),
                'documents': [{'id': d['document_id'], 'name': d['name']} for d in self.documents.values()],
                'topics': self.topics, 'edges': self.edges,
                'method': 'MiniBatchKMeans on normalized 384D embeddings; cosine top-3 topic neighbours',
                'labels_automatic': True}

    def fragment(self, index):
        chunk = self.chunks[int(index)]
        doc = self.documents[chunk['version_id']]
        return {'id': chunk['chunk_id'], 'topic_id': f'topic-{self.chunk_topics[int(index)]}',
                'document_id': doc['document_id'], 'document_name': doc['name'],
                'preview': chunk['text'][:220],
                'source_id': reference(doc, chunk['block_index'], chunk['start'], chunk['end'])['source_id']}

    def topic(self, topic_id):
        topic = next((t for t in self.topics if t['id'] == topic_id), None)
        if topic is None:
            raise KeyError(topic_id)
        index = int(topic_id.split('-')[1])
        members = self.members[index]
        scores = self.vectors[members] @ self.centres[index]
        ordered = members[np.argsort(-scores, kind='stable')[:40]]
        return {**topic, 'corpus_revision': self.revision['corpus_key'],
                'fragments': [self.fragment(i) for i in ordered], 'shown': len(ordered)}

    def neighbours(self, chunk_id):
        index = self.indices[chunk_id]
        scores = self.vectors @ self.vectors[index]
        selected = [int(i) for i in np.argsort(-scores, kind='stable') if i != index][:8]
        return {'corpus_revision': self.revision['corpus_key'], 'fragment': self.fragment(index),
                'neighbours': [{**self.fragment(i), 'similarity': round(float(scores[i]), 5)} for i in selected]}

    def question_topics(self, vector, model_revision):
        if model_revision != self.revision['model_revision']:
            return []
        scores = self.centres @ unit_matrix([vector])[0]
        return [{'id': f'topic-{int(i)}', 'similarity': round(float(scores[i]), 5)}
                for i in np.argsort(-scores, kind='stable')[:3]]


class KnowledgeMap:
    def __init__(self, store, embedder):
        self.store, self.embedder = store, embedder
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='knowledge-map')
        self._snapshot = None
        self._building = False
        self._failure = None
        self._failure_time = 0

    def _build(self, revision):
        try:
            if revision['model_revision'] != self.embedder.revision:
                raise MapUnavailable('Модель карты не совпадает с активным индексом.')
            key = revision['corpus_key']
            snapshot = Snapshot(revision, self.store.documents(key), self.store.snapshot_chunks(key))
            with self._lock:
                self._snapshot, self._failure = snapshot, None
        except Exception as exc:
            with self._lock:
                self._failure = (revision['corpus_key'], str(exc) if isinstance(exc, MapUnavailable) else
                                 'Не удалось построить карту. Повторите позже; поиск остаётся доступен.')
                self._failure_time = time.monotonic()
        finally:
            with self._lock:
                self._building = False

    def snapshot(self, expected=None):
        revision = self.store.active_revision()
        if expected and revision['corpus_key'] != expected:
            raise MapChanged('База обновилась. Обновите карту, чтобы открыть новую версию.')
        with self._lock:
            if self._snapshot and self._snapshot.revision['corpus_key'] == revision['corpus_key']:
                return self._snapshot
            if self._failure and self._failure[0] == revision['corpus_key'] and time.monotonic()-self._failure_time < 30:
                raise MapUnavailable(self._failure[1])
            if not self._building:
                self._building = True
                self._executor.submit(self._build, revision)
        raise MapBuilding('Карта строится локально по активному индексу.')

    def encode_question(self, question):
        from ..retrieval import query_parts
        parts = query_parts(question, self.embedder.tokenizer)
        vectors = self.embedder.encode(parts, query=True)
        vector = unit_matrix(vectors).mean(axis=0)
        return unit_matrix([vector])[0].tolist(), self.embedder.revision

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
