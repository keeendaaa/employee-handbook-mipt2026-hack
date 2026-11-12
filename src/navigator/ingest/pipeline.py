"""Local snapshot extraction and indexing. No cloud fallbacks."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from .chunking import PIPELINE_VERSION, chunk_document, digest


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def extract_corpus(directory: Path, output: Path, *, manifest: Path | None = None,
                   ocr: bool = True, timeout: int = 300) -> tuple[list[dict], dict]:
    if not directory.is_dir():
        raise ValueError("Каталог исходных файлов не существует")
    files = sorted(p for p in directory.iterdir() if not p.name.startswith("."))
    registry = {}
    missing = []
    expected_count = None
    if manifest:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        registry = {item["name"]: item for item in data["files"]}
        if len(registry) != len(data["files"]):
            raise ValueError("В реестре повторяются имена файлов")
        missing = sorted(set(registry) - {p.name for p in files})
        expected_count = data.get("expected_count", len(registry))
    report = {"pipeline_version": PIPELINE_VERSION, "status": "complete", "published": False,
              "expected_count": expected_count, "found_count": len(files),
              "missing_files": missing, "files": []}
    documents = []
    for path in files:
        item = {"name": path.name}
        try:
            if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= 100 * 1024**2:
                raise ValueError("Нужен обычный файл размером от 1 байта до 100 MiB")
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            meta = registry.get(path.name, {})
            if meta.get("sha256", sha) != sha:
                raise ValueError("SHA-256 не совпадает с реестром; проверьте файл и обновите реестр")
            document_id = meta.get("document_id", "local-" + digest(path.name)[:24])
            with tempfile.TemporaryDirectory(prefix="navigator-extract-") as scratch:
                target = Path(scratch) / "result.json"
                process = subprocess.Popen(
                    [sys.executable, "-m", "navigator.ingest.worker", str(path.resolve()),
                     str(target), "on" if ocr else "off"],
                    start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # OCR subprocesses must not outlive the bounded file worker.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    raise
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, "extract-worker")
                extracted = json.loads(target.read_text(encoding="utf-8"))
            if "error" in extracted:
                raise ValueError(extracted["error"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError("Оригинал изменился во время извлечения; повторите импорт")
            # Store extraction variants immutably even for identical original bytes.
            version_id = digest([document_id, sha, PIPELINE_VERSION, extracted])
            document = {"document_id": document_id, "version_id": version_id,
                        "sha256": sha, "name": path.name, **extracted}
            documents.append(document)
            write_json(output / "documents" / f"{version_id}.json", document)
            item.update(status="partial" if extracted["warnings"] else "complete",
                        version_id=version_id, document_id=document_id,
                        block_count=len(extracted["blocks"]), warnings=extracted["warnings"])
        except subprocess.TimeoutExpired:
            item.update(status="error", error="Превышен общий таймаут извлечения файла")
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            # OSError/subprocess text may contain arbitrary command details.
            item.update(status="error", error=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        report["files"].append(item)
    if not files or missing or any(item["status"] == "error" for item in report["files"]):
        report["status"] = "error"
    elif any(item["status"] == "partial" for item in report["files"]):
        report["status"] = "partial"
    if expected_count is not None and len(files) != expected_count:
        report["status"] = "error"
    if len({doc["document_id"] for doc in documents}) != len(documents):
        report["status"] = "error"
        report["error"] = "Повторяются идентификаторы документов"
    write_json(output / "report.json", report)
    return documents, report


def index_corpus(documents: list[dict], embedder, store) -> tuple[str, int]:
    chunks = []
    for document in documents:
        chunks.extend(chunk_document(document, embedder.tokenizer, embedder.revision))
    if not chunks:
        raise ValueError("Нет поисковых фрагментов")
    # Bounded batches keep temporary embeddings memory predictable.
    for start in range(0, len(chunks), 32):
        batch = chunks[start:start + 32]
        vectors = embedder.encode([chunk["embedding_text"] for chunk in batch])
        if len(vectors) != len(batch):
            raise RuntimeError("Модель вернула неверное число embeddings")
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk["embedding"] = vector
    corpus_key = digest([PIPELINE_VERSION, embedder.revision,
                         sorted(doc["version_id"] for doc in documents),
                         sorted(chunk["chunk_id"] for chunk in chunks)])
    return store.publish(documents, chunks, model_revision=embedder.revision, corpus_key=corpus_key), len(chunks)


def load_extraction(report_path: Path, originals: Path) -> tuple[list[dict], dict]:
    """Reuse auditable extraction artifacts without re-running expensive OCR."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") not in {"complete", "partial"} or report.get("missing_files"):
        raise ValueError("Отчёт содержит ошибки или отсутствующие файлы")
    if not report.get("files"):
        raise ValueError("Пустой отчёт извлечения")
    count = len(report["files"])
    if report.get("found_count", count) != count or report.get("expected_count") not in {None, count}:
        raise ValueError("Комплект файлов в отчёте неполный")
    documents = []
    for item in report["files"]:
        version = item["version_id"]
        if len(version) != 64 or any(c not in "0123456789abcdef" for c in version):
            raise ValueError("Некорректный ID версии в отчёте")
        doc = json.loads((report_path.parent / "documents" / f"{version}.json").read_text(encoding="utf-8"))
        if Path(doc["name"]).name != doc["name"]:
            raise ValueError("Некорректное имя оригинала")
        original = originals / doc["name"]
        if not original.is_file() or original.is_symlink() or hashlib.sha256(original.read_bytes()).hexdigest() != doc["sha256"]:
            raise ValueError("Оригинал отсутствует или изменился после извлечения")
        expected = digest([doc["document_id"], doc["sha256"], report["pipeline_version"],
                           {"blocks": doc["blocks"], "warnings": doc["warnings"]}])
        if doc["version_id"] != version or expected != version or doc["document_id"] != item["document_id"]:
            raise ValueError("Артефакт извлечения не совпадает с отчётом")
        documents.append(doc)
    return documents, report
