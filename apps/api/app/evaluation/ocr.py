"""One bounded local OCR invocation for a frozen, small image batch.

The default service FakeFixtureOcrAdapter is deliberately not used: returning
fixture ground truth is a routing test, not measured character recognition.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.extraction.deterministic import DeterministicExtractor
from app.extraction.validation import validate_extraction

from .metrics import field_metrics, rate
from .runner import bundle, canonical


def _language_part(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.isalpha() and value.islower()


def requested_language(cases: list[dict[str, Any]]) -> str:
    languages = {case.get("language") for case in cases}
    if len(languages) != 1:
        raise ValueError("OCR evaluation batch must use one explicit language configuration")
    language = next(iter(languages))
    if (
        not isinstance(language, str)
        or not language
        or any(not _language_part(part) for part in language.split("+"))
    ):
        raise ValueError("invalid OCR evaluation language configuration")
    return language


def available_languages(output: str) -> set[str]:
    return {
        line
        for raw in output.splitlines()
        if (line := raw.strip()) and _language_part(line)
    }


def split_pages(text: str, expected: int) -> list[str]:
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != expected:
        raise ValueError("OCR page count mismatch; refusing truncated batch")
    return [page.strip() for page in pages]


def synthetic_batch(cases: list[dict[str, Any]]) -> bool:
    flags = [case.get("synthetic") for case in cases]
    if not flags or any(type(flag) is not bool for flag in flags) or len(set(flags)) != 1:
        raise ValueError("OCR batch requires one explicit boolean synthetic provenance")
    return bool(flags[0])


async def run_command(*args: str, timeout: float) -> tuple[int, bytes]:
    """Reap children on both timeout and caller cancellation, including probes."""
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.communicate()
        raise
    return int(process.returncode or 0), output


async def score_text(text: str, expected: dict[str, Any]) -> dict[str, Any]:
    document = bundle(text, "ocr_evaluation")
    proposal = await DeterministicExtractor().extract(document)
    validation = validate_extraction(proposal, document)
    trusted = canonical(validation.fields.model_dump(mode="json")) if validation.fields else {}
    return {
        "field_metrics": field_metrics(canonical(proposal.output), expected),
        "downstream_valid": validation.valid,
        "trusted_field_metrics": field_metrics(trusted, expected),
    }


async def evaluate_ocr(directory: Path, *, page_segmentation_mode: int = 6) -> dict[str, Any]:
    if page_segmentation_mode not in {3, 6}:
        raise ValueError("OCR evaluation supports page segmentation mode 3 or 6")
    executable = shutil.which("tesseract")
    if not executable:
        return {
            "status": "not_run",
            "reason": "tesseract executable unavailable",
            "field_accuracy": None,
        }

    cases = json.loads((directory / "ocr_manifest.json").read_text(encoding="utf-8"))["cases"]
    if not 1 <= len(cases) <= 10:
        raise ValueError("OCR evaluation is restricted to 1-10 frozen images")
    language = requested_language(cases)
    synthetic = synthetic_batch(cases)

    images = [(directory / case["path"]).resolve() for case in cases]
    if any(not path.is_relative_to(directory.resolve()) for path in images):
        raise ValueError("unsafe OCR fixture path")
    if sum(path.stat().st_size for path in images) > 10 * 1024 * 1024:
        raise ValueError("OCR evaluation image budget exceeded")

    try:
        version_code, version_stdout = await run_command(executable, "--version", timeout=5)
        languages_code, languages_stdout = await run_command(
            executable, "--list-langs", timeout=5,
        )
    except TimeoutError:
        return {"status": "failed", "reason": "OCR probe timeout", "field_accuracy": None}
    if version_code or languages_code:
        return {
            "status": "not_run",
            "reason": "tesseract language discovery failed",
            "field_accuracy": None,
            "language": language,
        }

    installed = available_languages(languages_stdout.decode("utf-8", errors="replace"))
    missing = sorted(set(language.split("+")) - installed)
    if missing:
        return {
            "status": "not_run",
            "reason": "requested OCR language data unavailable: " + ",".join(missing),
            "field_accuracy": None,
            "language": language,
        }

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="procure-delta-ocr-") as temporary:
        listing = Path(temporary) / "images.txt"
        listing.write_text(
            "\n".join(str(path) for path in images) + "\n",
            encoding="utf-8",
        )
        try:
            code, output = await run_command(
                executable, str(listing), "stdout", "-l", language,
                "--psm", str(page_segmentation_mode), timeout=45,
            )
        except TimeoutError:
            return {
                "status": "failed",
                "reason": "OCR timeout",
                "field_accuracy": None,
                "language": language,
            }
        if code:
            return {
                "status": "failed",
                "reason": f"OCR exit {code}",
                "field_accuracy": None,
                "language": language,
            }

    elapsed = (time.perf_counter() - started) * 1000
    texts = split_pages(output.decode("utf-8"), len(cases))
    correct = trusted_correct = support = 0
    rows = []
    for case, text in zip(cases, texts, strict=True):
        scored = await score_text(text, case["expected_fields"])
        fields = scored["field_metrics"]
        correct += fields["correct"]
        trusted_correct += scored["trusted_field_metrics"]["correct"]
        support += fields["expected_fields"]
        rows.append(
            {
                "id": case["id"],
                "recognition_text": text,
                **scored,
            }
        )

    provider = (
        version_stdout.decode("utf-8", errors="replace").splitlines()[0]
        if version_stdout
        else "tesseract"
    )
    return {
        "status": "measured",
        "provider": provider,
        "language": language,
        "synthetic": synthetic,
        "page_segmentation_mode": page_segmentation_mode,
        "images": len(images),
        "actual_recognition_invocations": 1,
        "elapsed_ms": elapsed,
        "correct_fields": correct,
        "expected_fields": support,
        "field_accuracy": rate(correct, support),
        "trusted_correct_fields": trusted_correct,
        "trusted_field_accuracy": rate(trusted_correct, support),
        "rows": rows,
        "limitation": (
            "Frozen synthetic rendered images only; not production scans or complex layouts."
            if synthetic else
            "Public-source image evaluation; source preparation and scan provenance "
            "must be read from the calling suite, not inferred from this flag."
        ),
    }
