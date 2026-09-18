from datetime import UTC, datetime
from uuid import UUID

import pytest


def test_demo_phases_keep_amendment_on_same_notice_and_outcomes_separate():
    from app.demo.dataset import demo_records
    rows = demo_records('ci-123', datetime(2026, 9, 16, tzinfo=UTC), UUID(int=1))
    assert [r.raw_payload['lifecycle_stage'] for r in rows] == ['pre-specification', 'tender',
        'amendment', 'award', 'contract']
    assert rows[1].source_record_id == rows[2].source_record_id
    assert len({r.source_record_id for r in rows}) == 4
    assert rows[1].raw_payload['estimated_amount'] != rows[2].raw_payload['estimated_amount']
    assert rows[1].raw_payload['closes_at'] > rows[2].raw_payload['closes_at']
    assert all(r.raw_payload['is_synthetic'] for r in rows)
    assert (
        rows[3].raw_payload['official_references'][0]['source_record_id']
        == rows[2].source_record_id
    )


def test_demo_generation_reproducible_and_namespaced():
    from app.demo.dataset import demo_records
    now = datetime(2026, 9, 16, tzinfo=UTC)
    assert demo_records('review', now, UUID(int=1)) == demo_records('review', now, UUID(int=1))
    with pytest.raises(ValueError):
        demo_records('../unsafe', now, UUID(int=1))
    with pytest.raises(ValueError):
        demo_records('review', datetime(2026, 9, 16), UUID(int=1))


def test_demo_document_extraction_matches_upstream_fields():
    import asyncio

    from app.demo.dataset import demo_records, document_html
    from app.documents.parsers import _VisibleHTMLText
    from app.evaluation.runner import bundle
    from app.extraction.deterministic import DeterministicExtractor
    from app.extraction.validation import validate_extraction
    row = demo_records('ci', datetime(2026, 9, 16, tzinfo=UTC), UUID(int=1))[2]
    parser = _VisibleHTMLText()
    parser.feed(document_html(row).decode())
    text = "\n".join(parser.parts)
    document = bundle(text)
    result = asyncio.run(DeterministicExtractor().extract(document))
    report = validate_extraction(result, document)
    assert report.valid
    assert str(report.fields.estimated_amount) == '280000000'
    assert report.fields.regions == ['Seoul']
