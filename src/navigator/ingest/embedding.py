"""Explicit model download; inference never accesses the network."""

import hashlib
import json
import os
from pathlib import Path

MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"


def download_model(destination: Path) -> None:
    from huggingface_hub import snapshot_download

    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=destination,
        allow_patterns=["*.json", "*.safetensors", "*.model", "tokenizer*", "1_Pooling/*"],
    )
    files = {
        str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(destination.rglob("*"))
        if p.is_file() and ".cache" not in p.parts and p.name != "model-lock.json"
    }
    (destination / "model-lock.json").write_text(
        json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "files": files}, indent=2),
        encoding="utf-8",
    )


class LocalEmbedder:
    def __init__(self, path: Path):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        lock = json.loads((path / "model-lock.json").read_text(encoding="utf-8"))
        if lock["model_id"] != MODEL_ID or lock["revision"] != MODEL_REVISION:
            raise ValueError("Неподдерживаемая версия embedding-модели")
        if not lock["files"]:
            raise ValueError("Пустой реестр файлов модели")
        for name, expected in lock["files"].items():
            target = (path / name).resolve()
            if not target.is_relative_to(path.resolve()):
                raise ValueError("Некорректный путь в реестре модели")
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError("Контрольная сумма файла модели не совпадает")
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(str(path.resolve()), local_files_only=True, device="cpu")
        self.tokenizer = self.model.tokenizer
        self.revision = f"{MODEL_ID}@{MODEL_REVISION}"
        self.model.max_seq_length = 512

    def encode(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        prefix = "query: " if query else "passage: "
        inputs = [prefix + text for text in texts]
        if any(len(self.tokenizer.encode(text)) > 512 for text in inputs):
            raise ValueError("Текст превышает 512 токенов; молчаливое усечение запрещено")
        return self.model.encode(
            inputs, normalize_embeddings=True, batch_size=16, show_progress_bar=False
        ).tolist()
