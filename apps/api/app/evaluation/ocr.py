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


async def evaluate_ocr(directory: Path) -> dict[str, Any]:
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

    images = [(directory / case["path"]).resolve() for case in cases]
    if any(not path.is_relative_to(directory.resolve()) for path in images):
        raise ValueError("unsafe OCR fixture path")
    if sum(path.stat().st_size for path in images) > 10 * 1024 * 1024:
        raise ValueError("OCR evaluation image budget exceeded")

    version_proc = await asyncio.create_subprocess_exec(
        executable,
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    version_stdout, _ = await asyncio.wait_for(version_proc.communicate(), timeout=5)

    languages_proc = await asyncio.create_subprocess_exec(
        executable,
        "--list-langs",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    languages_stdout, _ = await asyncio.wait_for(languages_proc.communicate(), timeout=5)
    if languages_proc.returncode:
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
        process = await asyncio.create_subprocess_exec(
            executable,
            str(listing),
            "stdout",
            "-l",
            language,
            "--psm",
            "6",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=45)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return {
                "status": "failed",
                "reason": "OCR timeout",
                "field_accuracy": None,
                "language": language,
            }
        if process.returncode:
            return {
                "status": "failed",
                "reason": f"OCR exit {process.returncode}",
                "field_accuracy": None,
                "language": language,
            }

    elapsed = (time.perf_counter() - started) * 1000
    texts = split_pages(output.decode("utf-8"), len(cases))
    correct = support = 0
    rows = []
    for case, text in zip(cases, texts, strict=True):
        document = bundle(text, "tesseract")
        proposal = await DeterministicExtractor().extract(document)
        validation = validate_extraction(proposal, document)
        predicted = canonical(proposal.output)
        fields = field_metrics(predicted, case["expected_fields"])
        correct += fields["correct"]
        support += fields["expected_fields"]
        rows.append(
            {
                "id": case["id"],
                "recognition_text": text,
                "field_metrics": fields,
                "downstream_valid": validation.valid,
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
        "synthetic": True,
        "images": len(images),
        "actual_recognition_invocations": 1,
        "elapsed_ms": elapsed,
        "correct_fields": correct,
        "expected_fields": support,
        "field_accuracy": rate(correct, support),
        "rows": rows,
        "limitation": (
            "Frozen synthetic rendered images only; not production scans or complex layouts."
        ),
    }
