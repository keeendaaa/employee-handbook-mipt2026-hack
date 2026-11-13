"""One persistent import worker: local parsing, incremental embeddings, atomic publish."""

import hashlib
import logging
import os
from pathlib import Path
import threading
import time
import unicodedata

import psycopg

from ..ingest.chunking import PIPELINE_VERSION, chunk_document, digest
from ..ingest.embedding import LocalEmbedder
from ..ingest.pipeline import extract_corpus, write_json
from ..ingest.storage import Store, IndexConflictError
from .download import ImportFailure, download, filename
from .repository import ImportRepository

log = logging.getLogger(__name__)


def file_sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def process(job, store, repository, embedder, root):
    folder = root / str(job['id'])
    original = folder / 'original'
    original.mkdir(parents=True, exist_ok=True)
    paths = [p for p in original.iterdir() if p.is_file() and not p.name.startswith('.')]
    if job.get('source_url') and not paths:
        repository.update(job, 'downloading', 'Скачивание файла')
        path = download(job['source_url'], original)
    elif paths:
        path = paths[0]
        filename(path.name)
    else:
        raise ImportFailure('Оригинал файла недоступен. Загрузите его повторно.')
    sha = file_sha(path)
    active = store.active_revision()
    documents = store.documents(active['corpus_key'])
    same = next((doc for doc in documents if doc['sha256'] == sha), None)
    if same:
        repository.update(job, 'partial' if same['warnings'] else 'ready', 'Этот файл уже есть в общей базе. Дубликат не создан.', filename=path.name,
                          corpus_key=active['corpus_key'], document_id=same['document_id'], duplicate=True, warnings=same['warnings'])
        return
    named = next((doc for doc in documents if unicodedata.normalize('NFC', doc['name']).casefold() == path.name.casefold()), None)
    if named and not job['replace_existing']:
        raise ImportFailure('В базе уже есть другой файл с таким именем. Переименуйте файл или разрешите обновление существующего документа.')
    doc_id = named['document_id'] if named else 'uploaded-' + digest(path.name.casefold())[:24]
    manifest = folder / 'manifest.json'
    write_json(manifest, {'expected_count': 1, 'files': [{'name': path.name, 'sha256': sha, 'document_id': doc_id}]})
    repository.update(job, 'extracting', 'Чтение файла и распознавание сканов', filename=path.name)
    extracted, report = extract_corpus(original, folder / 'processed', manifest=manifest, timeout=300)
    if report['status'] == 'error' or len(extracted) != 1 or not extracted[0]['blocks']:
        raise ImportFailure('Не удалось извлечь текст из файла. Проверьте формат, повреждения, шифрование и читаемость скана.')
    document = extracted[0]
    if sum(len(block['text']) for block in document['blocks']) > 2_000_000:
        raise ImportFailure('Слишком большой объём текста для демонстрации. Разделите документ.')
    chunks = chunk_document(document, embedder.tokenizer, embedder.revision)
    if not chunks or len(chunks) > 2000:
        raise ImportFailure('Документ не содержит текста или превышает лимит 2000 поисковых фрагментов.')
    repository.update(job, 'indexing', f'Индексирование: {len(chunks)} новых фрагментов', filename=path.name, warnings=document['warnings'])
    started = time.monotonic()
    for index in range(0, len(chunks), 16):
        if time.monotonic() - started > 600:
            raise ImportFailure('Индексирование превысило лимит времени. Разделите документ.')
        batch = chunks[index:index + 16]
        vectors = embedder.encode([chunk['embedding_text'] for chunk in batch])
        if len(vectors) != len(batch):
            raise ImportFailure('Модель вернула неполный набор эмбеддингов.')
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk['embedding'] = vector
    for attempt in range(3):
        active = store.active_revision()
        if active['model_revision'] != embedder.revision:
            raise ImportFailure('Модель индекса изменилась. Повторите импорт после обновления сервиса.')
        existing = store.documents(active['corpus_key'])
        duplicate = next((doc for doc in existing if doc['sha256'] == sha), None)
        if duplicate:
            repository.update(job, 'partial' if duplicate['warnings'] else 'ready', 'Файл уже добавлен в общую базу.', filename=path.name,
                corpus_key=active['corpus_key'], document_id=duplicate['document_id'], duplicate=True, warnings=duplicate['warnings'])
            return
        conflict = next((doc for doc in existing if unicodedata.normalize('NFC', doc['name']).casefold() == path.name.casefold()), None)
        if conflict and (not job['replace_existing'] or conflict['document_id'] != doc_id):
            raise ImportFailure('База изменилась и теперь содержит файл с таким именем. Повторите импорт с явным разрешением обновления.')
        all_documents = [doc for doc in existing if doc['document_id'] != doc_id] + [document]
        all_chunks = [chunk for chunk in store.snapshot_chunks(active['corpus_key']) if chunk['document_id'] != doc_id] + chunks
        corpus_key = digest([PIPELINE_VERSION, embedder.revision, sorted(doc['version_id'] for doc in all_documents),
                             sorted(chunk['chunk_id'] for chunk in all_chunks)])
        try:
            store.publish(all_documents, all_chunks, model_revision=embedder.revision, corpus_key=corpus_key,
                          expected_active=active['corpus_key'])
            break
        except IndexConflictError:
            if attempt == 2:
                raise ImportFailure('База несколько раз изменилась во время импорта. Повторите позже.') from None
    status = 'partial' if report['status'] == 'partial' or document['warnings'] else 'ready'
    message = ('Документ обновлён.' if named else 'Документ добавлен в общую базу.')
    if status == 'partial':
        message += ' Есть предупреждения извлечения: доступный текст проиндексирован.'
    repository.update(job, status, message, filename=path.name, warnings=document['warnings'],
                      corpus_key=corpus_key, document_id=doc_id)


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import torch
    torch.set_num_threads(1)
    root = Path(os.environ.get('IMPORT_DIR', '/app/data/imports'))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(os.environ['DATABASE_URL'])
    store.init_schema()
    repository = ImportRepository(store)
    embedder = LocalEmbedder(Path(os.environ.get('MODEL_DIR', '/app/models/multilingual-e5-small')))
    while True:
        job = None
        stop = threading.Event()
        try:
            repository.heartbeat()
            job = repository.claim()
            if job is None:
                time.sleep(2)
                continue
            def heartbeat(current_job=job, current_stop=stop):
                while not current_stop.wait(15):
                    try:
                        repository.heartbeat(current_job['id'], current_job['owner'])
                    except psycopg.Error:
                        log.warning('Import heartbeat unavailable')
            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            try:
                process(job, store, repository, embedder, root)
            except Exception as exc:
                message = str(exc) if isinstance(exc, ImportFailure) else 'Техническая ошибка обработки файла. Повторите импорт или сообщите администратору.'
                repository.update(job, 'failed', message)
                log.warning('Import %s failed: %s', job['id'], type(exc).__name__)
            finally:
                stop.set()
                thread.join(timeout=2)
        except psycopg.Error:
            log.warning('Import database unavailable')
            time.sleep(5)


if __name__ == '__main__':
    main()
