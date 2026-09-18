from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from html import escape
from uuid import UUID

from app.sources.base import RawSourceRecord


def demo_records(run_id: str, anchor: datetime, source_id: UUID) -> list[RawSourceRecord]:
    if not re.fullmatch(r'[a-z0-9-]{1,32}', run_id):
        raise ValueError('run_id must be 1..32 lowercase letters, digits or hyphens')
    if anchor.tzinfo is None:
        raise ValueError('demo anchor must include timezone')
    anchor = anchor.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    phases = ['pre-specification', 'tender', 'amendment', 'award', 'contract']
    ids = [f'{run_id}-prespec', f'{run_id}-tender', f'{run_id}-tender', f'{run_id}-award',
        f'{run_id}-contract']
    records = []
    for index, stage in enumerate(phases):
        published = anchor - timedelta(days=5 - index)
        deadline = anchor + timedelta(days=20 if index < 2 else 12)
        previous = index - 1 if index > 0 else None
        if stage == 'amendment':
            previous = 0  # An amendment is a new version of the tender, not a self-link.
        refs = [] if previous is None else [{
            'source_id': str(source_id), 'source_record_id': ids[previous],
            'lifecycle_stage': phases[previous],
        }]
        fixture_key = f'lifecycle-demo:{anchor.date().isoformat()}:{run_id}:{index}'
        payload = {
            'title': f'Synthetic cloud document processing [{run_id}]',
            'buyer_name': 'Synthetic Seoul Digital Agency', 'procurement_type': 'services',
            'lifecycle_stage': stage, 'status': 'open' if index < 3 else 'closed',
            'published_at': published.isoformat(), 'effective_at': published.isoformat(),
            'closes_at': deadline.isoformat(),
            'estimated_amount': '320000000' if index < 2 else '280000000', 'currency': 'KRW',
            'regions': ['Seoul'], 'required_certifications': ['ISO 27001'],
            'required_capabilities': ['cloud migration', 'document processing'],
            'official_references': refs, 'is_synthetic': True,
            'demo_anchor': anchor.isoformat(), 'demo_run_id': run_id,
            'attachments': [{
                'attachment_id': f'{ids[index]}-{index}',
                'filename': f'{stage}.html',
                'url': f'https://example.invalid/lifecycle/{run_id}/{index}.html',
                'media_type': 'text/html', 'fixture_key': fixture_key,
            }],
        }
        records.append(RawSourceRecord(source_record_id=ids[index], raw_payload=payload,
                                        source_updated_at=published,
                                        source_url=(
                                            f'https://example.invalid/lifecycle/{run_id}/{index}'
                                        )))
    return records


def document_html(record: RawSourceRecord) -> bytes:
    fields = record.raw_payload
    lines = [
        'SYNTHETIC PROCUREMENT NOTICE - local demonstration only',
        'Title: ' + str(fields['title']), 'Buyer: ' + str(fields['buyer_name']),
        'Category: IT services', 'Budget: KRW ' + str(fields['estimated_amount']),
        'Published: ' + str(fields['published_at']), 'Deadline: ' + str(fields['closes_at']),
        'Region: ' + '; '.join(fields['regions']),
        'Certifications: ' + '; '.join(fields['required_certifications']),
        'Capabilities: ' + '; '.join(fields['required_capabilities']),
        'Fixture label: Synthetic data, not an actual procurement notice.',
    ]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body>'
            + ''.join('<p>' + escape(line) + '</p>' for line in lines) + '</body></html>').encode()


def resolve_demo_fixture(key: str) -> bytes:
    match = re.fullmatch(r'lifecycle-demo:(\d{4}-\d{2}-\d{2}):([a-z0-9-]{1,32}):([0-4])', key)
    if match is None:
        raise ValueError('unknown lifecycle demo fixture')
    date, run_id, index = match.groups()
    return document_html(demo_records(run_id, datetime.fromisoformat(date).replace(tzinfo=UTC),
                                      UUID(int=1))[int(index)])
