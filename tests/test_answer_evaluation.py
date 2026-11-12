"""Evaluation must reject bad anchors and forged citations rather than pass them."""

from pathlib import Path
import runpy

import pytest

from navigator.sources import reference

helpers = runpy.run_path(str(Path(__file__).parents[1] / 'misc' / 'scripts' / 'evaluate_answers.py'))


def sample():
    doc = {'document_id': 'synthetic', 'version_id': 'a' * 64, 'sha256': 'b' * 64,
           'name': 'СИНТЕТИЧЕСКИЙ документ', 'blocks': [{'text': '1. Подайте учебную заявку.\n2. Получите подтверждение.',
                                                       'locator': {'page': 1}, 'method': 'native'}]}
    case = {'supports': [{'document_id': 'synthetic', 'locator': {'page': 1}, 'needle': 'Подайте учебную заявку.'}]}
    return doc, case


def test_expected_evidence_is_canonical_and_missing_anchor_is_an_error():
    doc, case = sample()
    rows = helpers['reference_evidence'](case, {'synthetic': doc})
    assert rows[0]['text'] == doc['blocks'][0]['text']
    case['supports'][0]['needle'] = 'Неподтверждённый срок до 16:00'
    with pytest.raises(ValueError, match='fragment is absent'):
        helpers['reference_evidence'](case, {'synthetic': doc})


def test_forged_quote_and_unknown_claim_reference_fail_evaluation():
    doc, case = sample()
    ref = reference(doc, 0, 0, 25)
    response = {'summary': [{'text': 'Подайте учебную заявку.', 'citation_ids': [ref['source_id']]}],
                'steps': [], 'citations': [ref]}
    helpers['verify_response'](response, {'synthetic': doc})
    response['summary'][0]['citation_ids'] = ['invented']
    with pytest.raises(ValueError, match='invalid source link'):
        helpers['verify_response'](response, {'synthetic': doc})
    response['summary'][0]['citation_ids'] = [ref['source_id']]
    ref['quote'] = 'Выдуманный текст'
    with pytest.raises(ValueError, match='canonical source'):
        helpers['verify_response'](response, {'synthetic': doc})
