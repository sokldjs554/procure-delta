from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pymupdf
import pytest

from app.config import Settings
from app.documents.download import StoredAttachment
from app.documents.ocr import FakeFixtureOcrAdapter, OcrDocument
from app.documents.ocr_runtime import (
    RuntimeOcrConfig,
    TesseractOcrAdapter,
    configured_ocr_adapter,
    run_ocr_process,
)
from app.documents.parsers import parse_document

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux OCR worker runtime")


def document_from_bytes(content):
    attachment = StoredAttachment(hashlib.sha256(content).hexdigest(), len(content),
                                  "application/pdf", "untrusted-name.pdf", "test", content)
    return OcrDocument(attachment, parse_document(attachment))


def scanned_pdf(text="Runtime OCR document", pages=1):
    with pymupdf.open() as source, pymupdf.open() as scan:
        page = source.new_page(width=500, height=180)
        page.insert_text((30,60), text, fontsize=24)
        image = page.get_pixmap(dpi=150).tobytes("png")
        for _ in range(pages):
            target = scan.new_page(width=500,height=180)
            target.insert_image(target.rect, stream=image)
        return scan.tobytes()


def korean_scan():
    with pymupdf.open() as source, pymupdf.open() as scan:
        page = source.new_page(width=600, height=220)
        page.insert_text((30, 60), "사업명: 합성 문서 인식\n발주기관: 합성 연구소\n분류: 용역",
                         fontsize=24, fontname="korea")
        image = page.get_pixmap(dpi=150).tobytes("png")
        target = scan.new_page(width=600, height=220)
        target.insert_image(target.rect, stream=image)
        return scan.tobytes()


def model_directory():
    # Local developer override; CI installs the same supported language packages.
    import os
    directory = Path(os.getenv("TEST_TESSDATA_DIR", "/usr/share/tesseract-ocr/5/tessdata"))
    assert all((directory / f"{lang}.traineddata").is_file() for lang in ("kor", "eng")), (
        "Install Korean/English Tesseract language data; do not skip the real runtime test"
    )
    return directory


@pytest.mark.asyncio
async def test_real_ocr_recognizes_image_only_pdf_with_stable_provenance():
    config = RuntimeOcrConfig(tessdata_dir=model_directory())
    adapter = await TesseractOcrAdapter.create(config)
    same = await TesseractOcrAdapter.create(config)
    assert same.provider_version == adapter.provider_version
    document = document_from_bytes(scanned_pdf(pages=2))
    assert document.native_parse.extracted_text.strip() == ""
    result = await adapter.recognize(document)
    assert result.status == "recognized" and not result.synthetic
    assert result.provider == "tesseract_pymupdf"
    assert result.provider_version == adapter.provider_version
    assert [p.page_number for p in result.pages] == [1,2]
    assert all("Runtime OCR document" in p.text for p in result.pages)
    assert result.text_sha256 == hashlib.sha256(result.extracted_text.encode()).hexdigest()
    changed = await TesseractOcrAdapter.create(config.model_copy(update={"dpi": 150}))
    assert changed.provider_version != adapter.provider_version


@pytest.mark.asyncio
async def test_distinct_high_resolution_pages_fit_the_bounded_child():
    # Three distinct 600 dpi RGB scans: each decoded source is about 100 MiB,
    # although the PDF and 300 dpi recognition pages are within existing limits.
    # Reusing one image xref would hide accumulation in MuPDF's image cache.
    with pymupdf.open() as scan:
        for index in range(1, 4):
            with pymupdf.open() as source:
                page = source.new_page(width=595.68, height=842.4)
                page.insert_text((40, 70), f"Runtime page {index}", fontsize=24)
                page.insert_text((40, 120), "\n".join(
                    f"Service document item {line}: review the procurement requirements."
                    for line in range(1, 25)
                ), fontsize=13)
                image = page.get_pixmap(dpi=600).tobytes("jpg", jpg_quality=60)
                target = scan.new_page(width=595.68, height=842.4)
                xref = target.insert_image(target.rect, stream=image, keep_proportion=False)
                # Match a scanner's direct RGB image rather than a shared ICC profile.
                scan.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
        content = scan.tobytes()
    document = document_from_bytes(content)
    assert not document.native_parse.extracted_text.strip()
    adapter = await TesseractOcrAdapter.create(RuntimeOcrConfig(tessdata_dir=model_directory()))
    result = await adapter.recognize(document)
    assert result.status == "recognized"
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    for index, page in enumerate(result.pages, 1):
        assert f"Runtime page {index}" in page.text


@pytest.mark.asyncio
async def test_missing_language_data_fails_startup_without_fixture_fallback(tmp_path):
    with pytest.raises(RuntimeError, match="missing_language_data"):
        await configured_ocr_adapter(Settings(_env_file=None, ocr_backend="tesseract",
                                             ocr_tessdata_dir=tmp_path))


@pytest.mark.asyncio
async def test_real_korean_recognition_is_not_fixture_ground_truth():
    adapter = await TesseractOcrAdapter.create(RuntimeOcrConfig(tessdata_dir=model_directory()))
    document = document_from_bytes(korean_scan())
    assert not document.native_parse.extracted_text.strip()
    result = await adapter.recognize(document)
    compact = "".join(result.extracted_text.split())
    assert result.status == "recognized"
    # Runtime smoke only: the title's first word is misrecognized with some
    # model builds. Keep that quality limitation separate from process wiring.
    assert "문서인식" in compact and "합성연구소" in compact


def test_model_content_not_model_directory_controls_identity(tmp_path):
    from app.documents.ocr_process import runtime_identity

    for name in ("kor", "eng"):
        (tmp_path / f"{name}.traineddata").write_bytes(b"model-one")
    config = RuntimeOcrConfig(tessdata_dir=tmp_path)
    before = runtime_identity(config)
    second = tmp_path / "other"
    second.mkdir()
    for name in ("kor", "eng"):
        (second / f"{name}.traineddata").write_bytes(b"model-one")
    assert runtime_identity(config.model_copy(update={"tessdata_dir": second})) == before
    (second / "kor.traineddata").write_bytes(b"model-two")
    assert runtime_identity(config.model_copy(update={"tessdata_dir": second})) != before


@pytest.mark.asyncio
async def test_explicit_fixture_default_and_worker_startup_selection(monkeypatch):
    from app.workers import settings as workers

    settings = Settings(_env_file=None, ocr_backend="fixture")
    assert isinstance(await configured_ocr_adapter(settings), FakeFixtureOcrAdapter)
    marker = object()

    async def configured(value):
        assert value is settings
        return marker

    monkeypatch.setattr(workers, "get_settings", lambda: settings)
    monkeypatch.setattr(workers, "configured_ocr_adapter", configured)
    ctx = {}
    await workers.on_startup(ctx)
    assert ctx["ocr_adapter"] is marker


@pytest.mark.asyncio
@pytest.mark.parametrize("limits", [{"max_pages": 1}, {"max_pixels_per_page": 1000}])
async def test_limit_exceeding_pdf_is_not_partially_recognized(limits):
    adapter = await TesseractOcrAdapter.create(RuntimeOcrConfig(
        tessdata_dir=model_directory(), **limits,
    ))
    result = await adapter.recognize(document_from_bytes(scanned_pdf(pages=2)))
    assert result.status == "unavailable"
    assert result.pages == () and result.text_sha256 is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_kill_and_reap_real_child(tmp_path, cancel):
    pid_file = tmp_path / "pid"
    script = "import os,time,pathlib; pathlib.Path(%r).write_text(str(os.getpid())); time.sleep(30)"
    task = asyncio.create_task(run_ocr_process(
        [sys.executable, "-c", script % str(pid_file)], timeout=0.5 if not cancel else 10,
    ))
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    import os
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


@pytest.mark.asyncio
async def test_process_output_bound_does_not_echo_untrusted_text():
    with pytest.raises(RuntimeError, match="output_limit") as error:
        await run_ocr_process([sys.executable, "-c", "print('private-document-' * 200000)"],
                              timeout=3)
    assert "private-document" not in str(error.value)


@pytest.mark.asyncio
async def test_bad_child_output_cannot_become_partial_pages(monkeypatch):
    config = RuntimeOcrConfig(tessdata_dir=model_directory())
    adapter = await TesseractOcrAdapter.create(config)
    from app.documents import ocr_runtime

    async def truncated(*args, **kwargs):
        return json.dumps({"identity": adapter.identity, "pages": [
            {"page_number": 1, "text": "only one of two pages"},
        ]}).encode()

    monkeypatch.setattr(ocr_runtime, "run_ocr_process", truncated)
    with pytest.raises(RuntimeError, match="invalid_reply"):
        await adapter.recognize(document_from_bytes(scanned_pdf(pages=2)))


@pytest.mark.asyncio
async def test_shared_worker_adapter_serializes_recognition_children(monkeypatch):
    adapter = TesseractOcrAdapter(RuntimeOcrConfig(), "a" * 64)
    document = document_from_bytes(scanned_pdf())
    active = highest = 0

    async def invoke(*args, **kwargs):
        nonlocal active, highest
        active += 1
        highest = max(highest, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"identity": adapter.identity,
                "pages": [{"page_number": 1, "text": "Bounded runtime test"}]}

    monkeypatch.setattr(adapter, "_invoke", invoke)
    await asyncio.gather(*(adapter.recognize(document) for _ in range(3)))
    assert highest == 1
