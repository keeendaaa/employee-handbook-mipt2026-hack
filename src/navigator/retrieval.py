"""Bounded multi-query retrieval; it returns evidence candidates, not answers."""

from collections import Counter
import re

from .sources import reference


DOCUMENT_NUMBER = re.compile(
    r"\b(?:приказ(?:а|е|у|ом|ы|ов)?|распоряжени(?:е|я|и|ю|ем)|регламент(?:а|е|у|ом)?|поряд(?:ок|ка|ке|ку|ком))"
    r"\s*(?:[№#]|N(?:o|\.)?)?\s*(\d{1,6}(?:\s*[-–—]\s*\d{1,4})?)\b", re.I)


def document_numbers(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(1)).replace("–", "-").replace("—", "-")
            for m in DOCUMENT_NUMBER.finditer(text)}


def referenced_documents(query: str, documents: list[dict]) -> list[str]:
    """Filename references are search hints, never evidence of applicability."""
    requested = document_numbers(query)
    matched = []
    for doc in documents:
        known = document_numbers(doc["name"])
        leading = re.match(r"^(\d{1,6}[-–—]\d{1,4})(?=\s)", doc["name"])
        if leading:
            known.add(leading.group(1).replace("–", "-").replace("—", "-"))
        if requested & known:
            matched.append(doc["document_id"])
    return sorted(set(matched))


def query_parts(query: str, tokenizer) -> list[str]:
    if not isinstance(query, str) or not query.strip() or len(query) > 20000:
        raise ValueError("Запрос должен содержать от 1 до 20000 символов")
    query = query.strip()
    parts = []
    if len(tokenizer.encode("query: " + query, verbose=False)) <= 512:
        parts.append(query)
    # Preserve all content; no generated expansion or topic-specific synonym lists.
    spans = re.split(r"[?;\n]+\s*|(?<=\.)\s+|\s+(?:и|а также)\s+(?=(?:как|кто|когда|куда|где|что|какие|какой)\b)", query, flags=re.I)
    spans = [s.strip() for s in spans if s.strip()]
    if parts and len(spans) == 1:
        return parts
    for span in spans:
        span = span.strip()
        if not span:
            continue
        if len(tokenizer.encode("query: " + span, verbose=False)) <= 512:
            parts.append(span)
            continue
        offsets = tokenizer(span, add_special_tokens=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
        position = 0
        while position < len(offsets):
            end = min(position + 440, len(offsets))
            piece = span[offsets[position][0]:offsets[end - 1][1]]
            while len(tokenizer.encode("query: " + piece, verbose=False)) > 512:
                end = position + max(1, (end - position) // 2)
                piece = span[offsets[position][0]:offsets[end - 1][1]]
                if end - position == 1 and len(tokenizer.encode("query: " + piece, verbose=False)) > 512:
                    raise ValueError("Невозможно разбить запрос в пределах лимита модели")
            parts.append(piece)
            if end == len(offsets):
                break
            position = max(position + 1, end - 32)
    unique = list(dict.fromkeys(parts))
    if not unique or len(unique) > 32:
        raise ValueError("Запрос требует более 32 поисковых частей; разделите его на несколько сообщений")
    return unique


class RetrievalService:
    def __init__(self, store, embedder):
        self.store, self.embedder = store, embedder

    def search(self, query: str, limit: int = 10, *, mode: str = "hybrid", corpus_key: str | None = None) -> dict:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 30:
            raise ValueError("limit должен быть целым числом от 1 до 30")
        parts = query_parts(query, self.embedder.tokenizer)
        active = self.store.active_revision()
        if corpus_key is not None:
            active = {"corpus_key": corpus_key, "model_revision": self.embedder.revision}
        if active["model_revision"] != self.embedder.revision:
            raise ValueError("Модель не совпадает с активным индексом")
        vectors = self.embedder.encode(parts, query=True)
        documents = self.store.documents(active["corpus_key"])
        scores, by_id, matches, ranked_parts = Counter(), {}, {}, []
        scoped_candidates, document_hints = [], set()
        for part_index, (part, vector) in enumerate(zip(parts, vectors, strict=True)):
            rows = self.store.search(part, vector, limit=min(100, max(20, limit * 2)),
                                     model_revision=self.embedder.revision,
                                     corpus_key=active["corpus_key"], mode=mode)
            ranked_parts.append(rows)
            for rank, row in enumerate(rows, 1):
                key = row["chunk_id"]
                scores[key] += 1 / (60 + rank)
                by_id[key] = row
                matches.setdefault(key, []).append(part_index)
            hints = referenced_documents(part, documents) if mode != "dense" else []
            if hints:
                document_hints.update(hints)
                # The reference selects documents; its number must not reward
                # an unrelated numbered clause inside those documents.
                scoped_query = DOCUMENT_NUMBER.sub(" ", part).strip()
                if not scoped_query:
                    continue
                scoped = self.store.search(scoped_query, vector, limit=min(20, limit * 2),
                    model_revision=self.embedder.revision, corpus_key=active["corpus_key"],
                    mode="lexical", lexical_or=True, document_ids=hints)
                if scoped:
                    scoped_candidates.append(scoped[0])
                for rank, row in enumerate(scoped, 1):
                    key = row["chunk_id"]
                    # This is a dependent recall route, not independent evidence:
                    # do not boost a global candidate again for the same words.
                    scores.setdefault(key, 0.35 / (60 + rank))
                    by_id.setdefault(key, row)
                    if part_index not in matches.setdefault(key, []):
                        matches[key].append(part_index)
        candidates = sorted(by_id.values(), key=lambda r: (-scores[r["chunk_id"]], r["chunk_id"]))
        # Avoid filling the entire evidence budget with adjacent chunks of one page.
        selected, block_counts, selected_ids = [], Counter(), set()
        # Reserve one candidate per query part before global fusion. A compound
        # question must not spend its entire budget on the first subquestion.
        reserved = [rows[0] for rows in ranked_parts if rows] if len(parts) > 1 else []
        scoped_reserved = list({row["chunk_id"]: row for row in scoped_candidates}.values())[:max(1, limit // 5)]
        for row in scoped_reserved + reserved + candidates:
            key = (row["version_id"], row["block_index"])
            if row["chunk_id"] not in selected_ids and block_counts[key] < 2:
                selected.append(row)
                selected_ids.add(row["chunk_id"])
                block_counts[key] += 1
            if len(selected) == limit:
                break
        docs = {d["version_id"]: d for d in documents}
        for row in selected:
            document = docs[row["version_id"]]
            row["citation"] = reference(document, row["block_index"], row["start"], row["end"])
            row["matched_query_parts"] = matches[row["chunk_id"]]
            row["score"] = scores[row["chunk_id"]]
            block = document["blocks"][row["block_index"]]
            start, end = max(0, row["start"] - 600), min(len(block["text"]), row["end"] + 600)
            contexts = [(row["block_index"], start, end)]
            if block["kind"] in {"paragraph", "heading", "table_row", "sheet_row"}:
                for index in (row["block_index"] - 1, row["block_index"] + 1):
                    if 0 <= index < len(document["blocks"]):
                        neighbor = document["blocks"][index]
                        if neighbor["heading_path"] == block["heading_path"] and neighbor["kind"] == block["kind"]:
                            contexts.append((index, 0, min(len(neighbor["text"]), 1800)))
            row["context_sources"] = []
            for index, begin, finish in contexts:
                if not begin < finish:
                    continue
                ref = reference(document, index, begin, finish)
                row["context_sources"].append({"document_id": document["document_id"],
                    "locator": ref["locator"], "text": ref["quote"], "citation": ref})
        return {"corpus_revision": active["corpus_key"], "model_revision": self.embedder.revision,
                "retrieval_status": "candidates_found" if selected else "no_candidates",
                "answer_status": "not_assessed", "query_parts": parts,
                "referenced_document_hints": sorted(document_hints),
                "unrepresented_query_parts": sorted(set(range(len(parts))) - {
                    i for row in selected for i in row["matched_query_parts"]}),
                "limitations": ["Похожесть поиска не доказывает наличие ответа",
                                "Применимость редакций и полнота процедуры пока не проверяются"],
                "results": selected}
