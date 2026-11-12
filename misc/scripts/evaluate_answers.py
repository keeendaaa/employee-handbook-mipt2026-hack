"""Operator-only, sequential RAG evaluation; calls the configured paid model API."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

from navigator.evaluation import normalize, score_case
from navigator.generation import Generator
from navigator.ingest.embedding import LocalEmbedder
from navigator.ingest.pipeline import write_json
from navigator.ingest.storage import Store
from navigator.retrieval import RetrievalService
from navigator.sources import verify


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reference_evidence(case, documents):
    selected = {}
    for support in case.get('supports', []):
        doc = documents.get(support['document_id'])
        if doc is None:
            raise ValueError('Expected source document is absent')
        found = False
        for index, block in enumerate(doc['blocks']):
            if block['locator'] == support['locator'] and normalize(support['needle']) in normalize(block['text']):
                selected[(doc['version_id'], index)] = {
                    'document_id': doc['document_id'], 'document_name': doc['name'],
                    'locator': block['locator'], 'text': block['text'],
                }
                found = True
        if not found:
            raise ValueError('Expected source fragment is absent')
    return list(selected.values())


def verify_response(response, documents):
    versions = {doc['version_id']: doc for doc in documents.values()}
    for citation in response['citations']:
        if citation['version_id'] not in versions or not verify(versions[citation['version_id']], citation):
            raise ValueError('Citation does not match the canonical source')
    ids = {ref['source_id'] for ref in response['citations']}
    for claim in response['summary'] + response['steps']:
        if not claim['citation_ids'] or not set(claim['citation_ids']) <= ids:
            raise ValueError('Claim has an invalid source link')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, default=Path(os.environ.get('MODEL_DIR', 'models/multilingual-e5-small')))
    parser.add_argument('--case-id', action='append', default=[])
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text())
    if dataset.get('format_version') != 1:
        raise ValueError('Unsupported dataset')
    cases = [c for c in dataset['cases'] if not args.case_id or c['id'] in args.case_id]
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Need unique, nonempty cases')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', c['id']) for c in cases):
        raise ValueError('Invalid case identifier')
    model = os.environ['LLM_MODEL']
    key_path = os.environ.get('LLM_API_KEY_FILE')
    key = Path(key_path).read_text().strip() if key_path else os.environ.get('LLM_API_KEY', '')
    store = Store(os.environ['DATABASE_URL'])
    revision = store.active_revision()
    docs = {doc['document_id']: doc for doc in store.documents(revision['corpus_key'])}
    # Validate every source anchor before spending API credits.
    evidence = {c['id']: reference_evidence(c, docs) for c in cases}
    import navigator.retrieval, navigator.generation, navigator.campus
    code = {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (navigator.retrieval, navigator.generation, navigator.campus)}
    config = {'dataset_digest': digest(cases), 'model': model, 'corpus_revision': revision['corpus_key'], 'code': code}
    report = {'config': config, 'started_at': datetime.now(timezone.utc).isoformat(), 'complete': False,
              'semantic_review_status': 'not_assessed', 'independent_human_review': False, 'cases': []}
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        if previous['config'] != config:
            raise ValueError('Existing report belongs to another run configuration; choose another output')
        report = previous
        report['complete'] = False
    completed = {row['id']: row for row in report['cases'] if not row.get('technical_error')}
    rows = []
    import torch
    torch.set_num_threads(1)
    service = RetrievalService(store, LocalEmbedder(args.model_dir))
    generator = Generator(key, model=model, base_url=os.environ.get('LLM_BASE_URL', 'https://api.commandcode.ai/provider/v1'))
    try:
        for case in cases:
            if case['id'] in completed:
                rows.append(completed[case['id']])
                continue
            started = time.monotonic()
            row = {'id': case['id'], 'question': case['question'], 'expected_type': case['expected_type'],
                   'required_facts': case.get('required_facts', []), 'expected_evidence': evidence[case['id']],
                   'input_case_hash': digest(case)}
            stage = 'retrieval'
            try:
                retrieved = service.search(case['question'], limit=10, corpus_key=revision['corpus_key'])
                row['retrieval'] = score_case(case, retrieved['results'], list(docs.values()), 10)
                row['query_expansions'] = retrieved.get('query_expansions', [])
                stage = 'generation'
                response = generator.answer(case['question'], retrieved)
                stage = 'citation_verification'
                verify_response(response, docs)
                row.update(response=response, citations_verified=True,
                           response_type_matches_expected=response['result_type'] == case['expected_type'])
                row['cited_support_hits'] = [any(ref['document_id'] == support['document_id'] and
                    ref['locator'] == support['locator'] and normalize(support['needle']) in normalize(ref['quote'])
                    for ref in response['citations']) for support in case.get('supports', [])]
            except Exception as exc:
                row['technical_error'] = {'stage': stage, 'type': type(exc).__name__}
            row['seconds'] = round(time.monotonic() - started, 2)
            rows.append(row)
            # Retain later successful cases during a resumed run interrupted mid-way.
            report['cases'] = rows + [completed[c['id']] for c in cases[len(rows):] if c['id'] in completed]
            write_json(args.output, report)
            print(json.dumps({'id': row['id'], 'seconds': row['seconds'], 'status': 'error' if row.get('technical_error') else 'ok',
                              'actual_type': row.get('response', {}).get('result_type'),
                              'type_matches': row.get('response_type_matches_expected')}), flush=True)
    finally:
        generator.close()
    report['cases'] = rows
    report['complete'] = True
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    report['summary'] = {
        'cases': len(rows), 'technical_errors': sum(bool(row.get('technical_error')) for row in rows),
        'answer_types_match': sum(row.get('response_type_matches_expected', False) for row in rows),
        'citations_verified': sum(row.get('citations_verified', False) for row in rows),
        'positive_cases_all_expected_anchors_cited': sum(bool(row.get('cited_support_hits')) and all(row['cited_support_hits']) for row in rows),
        'usage_from_successful_responses': {name: sum(row.get('response', {}).get('usage', {}).get(name, 0) for row in rows)
                                            for name in ('prompt_tokens', 'completion_tokens')},
        'usage_incomplete_for_failed_calls': any(row.get('technical_error') for row in rows),
    }
    write_json(args.output, report)
    print(json.dumps(report['summary']), flush=True)
    return 1 if report['summary']['technical_errors'] else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError) as exc:
        print('Evaluation failed:', type(exc).__name__)
        raise SystemExit(1) from None
