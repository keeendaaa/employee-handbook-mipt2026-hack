"""Token-budgeted exact source slices, without decode/re-encode text loss."""

import hashlib
import json

PIPELINE_VERSION = "ingest-v2"


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def chunk_document(document: dict, tokenizer, model_revision: str) -> list[dict]:
    chunks = []
    for block_index, block in enumerate(document["blocks"]):
        text = block["text"]
        if not text.strip():
            continue
        # Fast-tokenizer offsets refer to the original string, not decoded token text.
        offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
        start = 0
        while start < len(text):
            candidates = [end for _, end in offsets if end > start]
            if not candidates:
                end = len(text)
            else:
                # Leave room for prefix and special tokens; validate the actual input below.
                end = candidates[min(449, len(candidates) - 1)]
                if len(candidates) <= 450:
                    end = len(text)
                else:
                    # Prefer a paragraph/sentence boundary while keeping an exact source slice.
                    floor = start + (end - start) * 2 // 3
                    boundary = max(text.rfind("\n", floor, end), text.rfind(". ", floor, end))
                    if boundary >= floor:
                        end = boundary + 1
            while len(tokenizer.encode("passage: " + text[start:end])) > 512:
                end = start + (end - start) // 2
                if end <= start:
                    raise ValueError("Невозможно разбить блок в пределах лимита токенов")
            if text[start:end].strip():
                chunk = {
                    "document_id": document["document_id"],
                    "version_id": document["version_id"],
                    "block_index": block_index,
                    "text": text[start:end],
                    "start": start,
                    "end": end,
                    "locator": block["locator"],
                    "heading_path": block["heading_path"],
                }
                prefix = "\n".join([document.get("name", ""), *block["heading_path"]]).strip()
                while prefix and len(tokenizer.encode("passage: " + prefix + "\n" + chunk["text"])) > 512:
                    prefix = prefix[:len(prefix) // 2].rstrip()
                chunk["embedding_text"] = (prefix + "\n" if prefix else "") + chunk["text"]
                chunk["chunk_id"] = digest([PIPELINE_VERSION, model_revision, chunk])
                chunks.append(chunk)
            start = end
    return chunks
