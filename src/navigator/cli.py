"""Operator CLI; source text is printed only by explicit search."""

import argparse
import json
import os
from pathlib import Path
import sys

from .ingest.pipeline import extract_corpus, index_corpus, write_json


def parser():
    root = argparse.ArgumentParser(prog="navigator", description="Локальный импорт документов")
    commands = root.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download-model", help="Явно скачать E5; нужен интернет")
    download.add_argument("--model-dir", type=Path, default=Path("models/multilingual-e5-small"))
    commands.add_parser("db-init", help="Создать схему PostgreSQL")
    index = commands.add_parser("index", help="Индексировать проверенные артефакты без повторного OCR")
    index.add_argument("--report", type=Path, required=True)
    index.add_argument("--input", type=Path, default=Path("data/raw"))
    index.add_argument("--model-dir", type=Path, default=Path("models/multilingual-e5-small"))
    index.add_argument("--allow-warnings", action="store_true")
    audit = commands.add_parser("audit", help="Проверить целостность и ограничения извлечения без модели")
    audit.add_argument("--report", type=Path, required=True)
    audit.add_argument("--input", type=Path, default=Path("data/raw"))
    audit.add_argument("--output", type=Path, required=True)
    for command in ("extract", "ingest"):
        sub = commands.add_parser(command)
        sub.add_argument("--input", type=Path, default=Path("data/raw"))
        sub.add_argument("--output", type=Path, default=Path("data/processed"))
        sub.add_argument("--manifest", type=Path)
        sub.add_argument("--no-ocr", action="store_true")
        sub.add_argument("--timeout", type=int, default=300)
        if command == "ingest":
            sub.add_argument("--model-dir", type=Path, default=Path("models/multilingual-e5-small"))
            sub.add_argument("--allow-warnings", action="store_true",
                             help="Индексировать доступные блоки с сохранением предупреждений")
    search = commands.add_parser("search", help="Поиск фрагментов без генерации ответа")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--model-dir", type=Path, default=Path("models/multilingual-e5-small"))
    search.add_argument("--baseline", action="store_true", help="Исходный поиск без разбиения вопроса и контекста")
    search.add_argument("--mode", choices=["hybrid", "dense", "lexical"], default="hybrid")
    search.add_argument("--output", type=Path, help="Сохранить фрагменты локально вместо печати")
    source = commands.add_parser("source", help="Открыть точную цитату по source_id без загрузки модели")
    source.add_argument("source_id")
    source.add_argument("--output", type=Path)
    evaluation = commands.add_parser("evaluate", help="Проверить поиск на локальных эталонных фрагментах")
    evaluation.add_argument("--dataset", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    evaluation.add_argument("--mode", choices=["baseline", "hybrid", "dense", "lexical"], default="hybrid")
    evaluation.add_argument("--k", type=int, default=10)
    evaluation.add_argument("--model-dir", type=Path, default=Path("models/multilingual-e5-small"))
    return root


def get_store():
    from .ingest.storage import Store

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise ValueError("Задайте DATABASE_URL для локального PostgreSQL")
    return Store(dsn)


def run(args) -> int:
    if args.command == "audit":
        from .audit import audit_documents
        from .ingest.pipeline import load_extraction

        docs, _ = load_extraction(args.report, args.input)
        report = audit_documents(docs)
        write_json(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k != "documents"}, ensure_ascii=False))
        return 0
    if args.command == "index":
        from .ingest.chunking import PIPELINE_VERSION
        from .ingest.embedding import LocalEmbedder
        from .ingest.pipeline import load_extraction

        docs, report = load_extraction(args.report, args.input)
        if report["status"] == "partial" and not args.allow_warnings:
            print("Есть предупреждения: проверьте отчёт и передайте --allow-warnings.")
            return 2
        try:
            store = get_store()
            store.init_schema()
            embedder = LocalEmbedder(args.model_dir)
            key, count = index_corpus(docs, embedder, store)
        except Exception as exc:
            report.update(published=False, index_error=type(exc).__name__)
            write_json(args.report, report)
            raise
        report.pop("index_error", None)
        report.update(published=True, corpus_revision=key, chunk_count=count,
                      index_pipeline_version=PIPELINE_VERSION, model_revision=embedder.revision)
        write_json(args.report, report)
        print(json.dumps({"published": True, "documents": len(docs), "chunks": count, "corpus_revision": key}))
        return 0
    if args.command == "source":
        from .sources import resolve

        result = resolve(get_store(), args.source_id)
        if args.output:
            write_json(args.output, result)
            print("Источник сохранён локально.")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "evaluate":
        from .evaluation import evaluate
        from .ingest.embedding import LocalEmbedder
        from .retrieval import RetrievalService

        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        if dataset.get("format_version") != 1:
            raise ValueError("Неподдерживаемая версия проверочного набора")
        if not 1 <= args.k <= (100 if args.mode == "baseline" else 30):
            raise ValueError("k должен быть от 1 до 30 (до 100 для baseline)")
        cases = [c for c in dataset["cases"] if args.split == "all" or c.get("split") == args.split]
        store, embedder = get_store(), LocalEmbedder(args.model_dir)
        active = store.active_revision()
        service = RetrievalService(store, embedder)
        if args.mode == "baseline":
            def retrieve(question, k):
                return store.search(question, embedder.encode([question], query=True)[0], k,
                                    corpus_key=active["corpus_key"], model_revision=embedder.revision)
        else:
            def retrieve(question, k):
                return service.search(question, k, mode=args.mode, corpus_key=active["corpus_key"])["results"]
        report = evaluate(cases, retrieve, store.documents(active["corpus_key"]), args.k)
        report.update(corpus_revision=active["corpus_key"], model_revision=embedder.revision,
                      mode=args.mode, split=args.split, corpus_kind=dataset.get("corpus_kind", "unspecified"))
        write_json(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False))
        return 1 if report["technical_error_count"] else 0
    if args.command == "download-model":
        from .ingest.embedding import download_model

        download_model(args.model_dir)
        print("Модель скачана, контрольные суммы сохранены.")
        return 0
    if args.command == "db-init":
        get_store().init_schema()
        print("Схема БД подготовлена.")
        return 0
    if args.command in {"extract", "ingest"}:
        if not 1 <= args.timeout <= 3600:
            raise ValueError("Таймаут должен быть от 1 до 3600 секунд на файл")
        # Never let extraction artifacts overwrite originals.
        original, output = args.input.resolve(), args.output.resolve()
        if output == original or output.is_relative_to(original) or original.is_relative_to(output):
            raise ValueError("Каталоги оригиналов и результатов должны быть отдельными")
        docs, report = extract_corpus(args.input, args.output, manifest=args.manifest,
                                      ocr=not args.no_ocr, timeout=args.timeout)
        if args.command == "ingest" and report["status"] != "error":
            if report["status"] == "partial" and not args.allow_warnings:
                print("Есть предупреждения. Проверьте report.json; публикация требует --allow-warnings.")
            else:
                try:
                    from .ingest.embedding import LocalEmbedder

                    store = get_store()
                    store.init_schema()
                    embedder = LocalEmbedder(args.model_dir)
                    key, count = index_corpus(docs, embedder, store)
                    report.update(published=True, corpus_revision=key, chunk_count=count,
                                  model_revision=embedder.revision)
                except Exception as exc:
                    report.update(index_error=type(exc).__name__, published=False,
                                  extraction_status=report["status"], status="error")
                    write_json(args.output / "report.json", report)
                    raise
                write_json(args.output / "report.json", report)
        print(json.dumps({"status": report["status"], "files": len(report["files"]),
                          "errors": sum(f["status"] == "error" for f in report["files"]),
                          "published": report["published"], "report": str(args.output / "report.json")},
                         ensure_ascii=False))
        if report["status"] == "error":
            return 1
        if args.command == "ingest" and report["published"]:
            return 0
        return 2 if report["status"] == "partial" else 0
    if not args.query.strip() or not 1 <= args.limit <= 100:
        raise ValueError("Нужен непустой вопрос и limit от 1 до 100")
    from .ingest.embedding import LocalEmbedder

    store = get_store()
    if not args.baseline:
        from .retrieval import RetrievalService

        result = RetrievalService(store, LocalEmbedder(args.model_dir)).search(args.query, args.limit, mode=args.mode)
        if args.output:
            write_json(args.output, result)
            print(json.dumps({"results": len(result["results"]), "corpus_revision": result["corpus_revision"]}))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    active = store.active_revision()
    embedder = LocalEmbedder(args.model_dir)
    if active["model_revision"] != embedder.revision:
        raise ValueError("Модель не совпадает с активным индексом")
    vector = embedder.encode([args.query], query=True)[0]
    results = store.search(args.query, vector, args.limit, model_revision=embedder.revision, mode=args.mode)
    revision = results[0]["corpus_revision"] if results else store.active_revision()["corpus_key"]
    result = {"corpus_revision": revision, "results": results}
    if args.output:
        write_json(args.output, result)
        print(json.dumps({"results": len(results), "corpus_revision": revision}))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main():
    args = parser().parse_args()
    try:
        code = run(args)
    except Exception as exc:
        # Do not expose DSN credentials, parser payloads or SQL in terminal errors.
        message = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else "Проверьте доступность БД, модель и локальный отчёт импорта"
        print(f"Ошибка ({type(exc).__name__}): {message}", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
