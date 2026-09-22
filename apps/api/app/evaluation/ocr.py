"""One bounded local OCR invocation for a frozen, small image batch.

The default service FakeFixtureOcrAdapter is deliberately not used: returning
fixture ground truth is a routing test, not measured character recognition.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from app.extraction.deterministic import DeterministicExtractor
from app.extraction.validation import validate_extraction

from .metrics import field_metrics, rate
from .runner import bundle, canonical


_LANGUAGE_PATTERN = re.compile(r'^[a-z]{3}(?:\\+[a-z]{3})*    pages = text.split('\f')
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != expected:
        raise ValueError('OCR page count mismatch; refusing truncated batch')
    return [page.strip() for page in pages]


async def evaluate_ocr(directory: Path) -> dict[str, Any]:
    executable = shutil.which('tesseract')
    if not executable:
        return {'status': 'not_run', 'reason': 'tesseract executable unavailable',
                'field_accuracy': None}
    cases = json.loads((directory / 'ocr_manifest.json').read_text())['cases']
    if not 1 <= len(cases) <= 10:
        raise ValueError('OCR evaluation is restricted to 1-10 frozen images')
    language = requested_language(cases)
    images = [(directory / case['path']).resolve() for case in cases]
    if any(not p.is_relative_to(directory.resolve()) for p in images):
        raise ValueError('unsafe OCR fixture path')
    if sum(p.stat().st_size for p in images) > 10 * 1024 * 1024:
        raise ValueError('OCR evaluation image budget exceeded')
    version_proc = await asyncio.create_subprocess_exec(
        executable, '--version', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    version_stdout, _ = await asyncio.wait_for(version_proc.communicate(), 5)
    languages_proc = await asyncio.create_subprocess_exec(
        executable, '--list-langs',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    languages_stdout, _ = await asyncio.wait_for(languages_proc.communicate(), 5)
    installed = available_languages(languages_stdout.decode('utf-8', errors='replace'))
    missing = sorted(set(language.split('+')) - installed)
    if missing:
        return {
            'status': 'not_run',
            'reason': 'requested OCR language data unavailable: ' + ','.join(missing),
            'field_accuracy': None,
            'language': language,
        }
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='procure-delta-ocr-') as temporary:
        listing = Path(temporary) / 'images.txt'
        listing.write_text('\n'.join(str(p) for p in images) + '\n', encoding='utf-8')
        process = await asyncio.create_subprocess_exec(
            executable, str(listing), 'stdout', '-l', language, '--psm', '6',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=45)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return {'status': 'failed', 'reason': 'OCR timeout', 'field_accuracy': None}
        if process.returncode:
            return {'status': 'failed', 'reason': f'OCR exit {process.returncode}',
                    'field_accuracy': None}
    elapsed = (time.perf_counter() - started) * 1000
    texts = split_pages(output.decode('utf-8'), len(cases))
    correct = support = 0
    rows = []
    for case, text in zip(cases, texts, strict=True):
        document = bundle(text, 'tesseract')
        proposal = await DeterministicExtractor().extract(document)
        validation = validate_extraction(proposal, document)
        predicted = canonical(proposal.output)
        fields = field_metrics(predicted, case['expected_fields'])
        correct += fields['correct']
        support += fields['expected_fields']
        rows.append({'id': case['id'], 'recognition_text': text,
                     'field_metrics': fields, 'downstream_valid': validation.valid})
    return {
        'status': 'measured', 'provider': version_stdout.decode().splitlines()[0],
        'language': language, 'synthetic': True, 'images': len(images),
        'actual_recognition_invocations': 1, 'elapsed_ms': elapsed,
        'correct_fields': correct, 'expected_fields': support,
        'field_accuracy': rate(correct, support), 'rows': rows,
        'limitation': (
            'Frozen synthetic rendered images only; not production scans or complex layouts.'
        ),
    }
)


def requested_language(cases: list[dict[str, Any]]) -> str:
    languages = {case.get('language') for case in cases}
    if len(languages) != 1:
        raise ValueError('OCR evaluation batch must use one explicit language configuration')
    language = next(iter(languages))
    if not isinstance(language, str) or not _LANGUAGE_PATTERN.fullmatch(language):
        raise ValueError('invalid OCR evaluation language configuration')
    return language


def available_languages(output: str) -> set[str]:
    return {
        line.strip()
        for line in output.splitlines()
        if re.fullmatch(r'[a-z]{3}', line.strip())
    }


def split_pages(text: str, expected: int) -> list[str]:
    pages = text.split('\f')
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != expected:
        raise ValueError('OCR page count mismatch; refusing truncated batch')
    return [page.strip() for page in pages]


async def evaluate_ocr(directory: Path) -> dict[str, Any]:
    executable = shutil.which('tesseract')
    if not executable:
        return {'status': 'not_run', 'reason': 'tesseract executable unavailable',
                'field_accuracy': None}
    cases = json.loads((directory / 'ocr_manifest.json').read_text())['cases']
    if not 1 <= len(cases) <= 10:
        raise ValueError('OCR evaluation is restricted to 1-10 frozen images')
    images = [(directory / case['path']).resolve() for case in cases]
    if any(not p.is_relative_to(directory.resolve()) for p in images):
        raise ValueError('unsafe OCR fixture path')
    if sum(p.stat().st_size for p in images) > 10 * 1024 * 1024:
        raise ValueError('OCR evaluation image budget exceeded')
    version_proc = await asyncio.create_subprocess_exec(
        executable, '--version', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    version_stdout, _ = await asyncio.wait_for(version_proc.communicate(), 5)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='procure-delta-ocr-') as temporary:
        listing = Path(temporary) / 'images.txt'
        listing.write_text('\n'.join(str(p) for p in images) + '\n', encoding='utf-8')
        process = await asyncio.create_subprocess_exec(
            executable, str(listing), 'stdout', '-l', 'eng', '--psm', '6',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=45)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return {'status': 'failed', 'reason': 'OCR timeout', 'field_accuracy': None}
        if process.returncode:
            return {'status': 'failed', 'reason': f'OCR exit {process.returncode}',
                    'field_accuracy': None}
    elapsed = (time.perf_counter() - started) * 1000
    texts = split_pages(output.decode('utf-8'), len(cases))
    correct = support = 0
    rows = []
    for case, text in zip(cases, texts, strict=True):
        document = bundle(text, 'tesseract')
        proposal = await DeterministicExtractor().extract(document)
        validation = validate_extraction(proposal, document)
        predicted = canonical(proposal.output)
        fields = field_metrics(predicted, case['expected_fields'])
        correct += fields['correct']
        support += fields['expected_fields']
        rows.append({'id': case['id'], 'recognition_text': text,
                     'field_metrics': fields, 'downstream_valid': validation.valid})
    return {
        'status': 'measured', 'provider': version_stdout.decode().splitlines()[0],
        'language': 'eng', 'synthetic': True, 'images': len(images),
        'actual_recognition_invocations': 1, 'elapsed_ms': elapsed,
        'correct_fields': correct, 'expected_fields': support,
        'field_accuracy': rate(correct, support), 'rows': rows,
        'limitation': 'English rendered images only; not Korean scans, layouts or production OCR.',
    }
