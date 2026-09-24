"""Configured OCR boundary with one cancellable, resource-bounded process per PDF."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.documents.ocr import FakeFixtureOcrAdapter, OcrAdapter, OcrDocument, OcrResult
from app.documents.parsers import ParsedPage

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_REPLY_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 250_000
PROCESS_MEMORY_BYTES = 512 * 1024 * 1024
RUNTIME_ADAPTER_VERSION = "pymupdf-ocr-v2"


class RuntimeOcrConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tessdata_dir: Path = Path("/usr/share/tesseract-ocr/5/tessdata")
    language: Literal["kor+eng", "kor", "eng"] = "kor+eng"
    dpi: int = Field(default=300, ge=72, le=300)
    max_pages: int = Field(default=10, ge=1, le=30)
    max_pixels_per_page: int = Field(default=12_000_000, ge=1, le=20_000_000)
    timeout_seconds: float = Field(default=40, ge=1, le=45)


async def run_ocr_process(args: list[str], *, timeout: float) -> bytes:
    """Limit output/deadline and reap the child, including caller cancellation."""
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    try:
        async with asyncio.timeout(timeout):
            assert process.stdout is not None
            output = bytearray()
            while chunk := await process.stdout.read(65536):
                output.extend(chunk)
                if len(output) > MAX_REPLY_BYTES:
                    raise RuntimeError("OCR output_limit")
            code = await process.wait()
            if code:
                raise RuntimeError("OCR process_failed")
            return bytes(output)
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        # Drain the bounded pipe after killing too; wait alone can deadlock when
        # the stream transport has paused on an output-limit failure.
        await process.communicate()


class TesseractOcrAdapter:
    provider = "tesseract_pymupdf"

    def __init__(self, config: RuntimeOcrConfig, identity: str) -> None:
        self.config = config
        self.identity = identity
        self.provider_version = RUNTIME_ADAPTER_VERSION + "-" + identity
        self._slot = asyncio.Semaphore(1)

    @classmethod
    async def create(cls, config: RuntimeOcrConfig) -> TesseractOcrAdapter:
        if sys.platform != "linux":
            raise RuntimeError("Tesseract runtime requires the Linux worker image")
        reply = await cls._invoke(config, "--probe", timeout=10)
        identity = reply.get("identity")
        if (not isinstance(identity, str) or len(identity) != 64
                or any(c not in "0123456789abcdef" for c in identity)):
            raise RuntimeError("OCR invalid_reply")
        return cls(config, identity)

    @staticmethod
    async def _invoke(
        config: RuntimeOcrConfig, *args: str, timeout: float,
    ) -> dict[str, object]:
        output = await run_ocr_process([
            sys.executable, "-m", "app.documents.ocr_process", "--config",
            config.model_dump_json(), *args,
        ], timeout=timeout)
        try:
            reply = json.loads(output)
        except (ValueError, UnicodeDecodeError) as error:
            raise RuntimeError("OCR invalid_reply") from error
        if not isinstance(reply, dict):
            raise RuntimeError("OCR invalid_reply")
        if "error" in reply:
            reason = reply["error"]
            if reason in {"page_limit", "pixel_limit", "input_limit", "unsupported_pdf"}:
                return {"unavailable": True}
            known = reason if reason in {"missing_language_data", "runtime_failed"} else "failed"
            raise RuntimeError(f"OCR {known}")
        return reply

    async def recognize(self, document: OcrDocument) -> OcrResult:
        synthetic = document.fixture_key is not None

        def unavailable() -> OcrResult:
            return OcrResult(self.provider, self.provider_version, synthetic, (), "", None,
                             "unavailable")

        content = document.attachment.original_bytes
        if document.attachment.media_type != "application/pdf" or len(content) > MAX_INPUT_BYTES:
            return unavailable()
        async with self._slot:
            with tempfile.TemporaryDirectory(prefix="procure-delta-ocr-") as temporary:
                source = Path(temporary) / "input.pdf"
                source.write_bytes(content)
                reply = await self._invoke(self.config, "--pdf", str(source),
                                           timeout=self.config.timeout_seconds)
        if reply.get("unavailable") is True:
            return unavailable()
        raw_pages = reply.get("pages")
        expected = document.native_parse.page_count
        if (reply.get("identity") != self.identity or not isinstance(raw_pages, list)
                or not 1 <= expected <= self.config.max_pages or len(raw_pages) != expected):
            raise RuntimeError("OCR invalid_reply")
        pages = []
        total = 0
        for index, page in enumerate(raw_pages, 1):
            if (not isinstance(page, dict) or type(page.get("page_number")) is not int
                    or page["page_number"] != index or not isinstance(page.get("text"), str)):
                raise RuntimeError("OCR invalid_reply")
            total += len(page["text"])
            if total > MAX_TEXT_CHARS:
                raise RuntimeError("OCR output_limit")
            pages.append(ParsedPage(index, page["text"]))
        text = "\n\n".join(page.text for page in pages)
        return OcrResult(self.provider, self.provider_version, synthetic, tuple(pages), text,
                         hashlib.sha256(text.encode()).hexdigest(), "recognized")


async def configured_ocr_adapter(settings: Settings) -> OcrAdapter:
    if settings.ocr_backend == "fixture":
        return FakeFixtureOcrAdapter()
    return await TesseractOcrAdapter.create(RuntimeOcrConfig(
        tessdata_dir=settings.ocr_tessdata_dir, language=settings.ocr_language,
        dpi=settings.ocr_dpi, max_pages=settings.ocr_max_pages,
        max_pixels_per_page=settings.ocr_max_pixels_per_page,
        timeout_seconds=settings.ocr_timeout_seconds,
    ))
