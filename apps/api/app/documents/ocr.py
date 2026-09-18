from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.documents.download import StoredAttachment
from app.documents.parsers import ParsedDocument, ParsedPage
from app.documents.quality import TextQuality
from app.documents.synthetic_fixtures import (
    SYNTHETIC_SCANNED_GROUND_TRUTH,
    load_packaged_fixture,
)

OCR_FAKE_VERSION = "ocr-fixture-fake-v1"


@dataclass(frozen=True, slots=True)
class OcrDocument:
    attachment: StoredAttachment
    native_parse: ParsedDocument
    fixture_key: str | None = None


@dataclass(frozen=True, slots=True)
class OcrResult:
    provider: str
    provider_version: str
    synthetic: bool
    pages: tuple[ParsedPage, ...]
    extracted_text: str
    text_sha256: str | None
    status: str


@runtime_checkable
class OcrAdapter(Protocol):
    """Provider boundary for local fixtures or a configured real OCR service."""

    provider: str
    provider_version: str

    async def recognize(self, document: OcrDocument) -> OcrResult: ...


def should_use_ocr(quality: TextQuality) -> bool:
    """Route only supported low-quality native parses to OCR."""
    return quality.status == "needs_ocr"


def ocr_parser_version(provider: str, provider_version: str) -> str:
    """Build a bounded durable identity from provider and provider-local version."""
    identity = f"{provider}\x00{provider_version}".encode()
    return f"ocr-{hashlib.sha256(identity).hexdigest()}"


class FakeFixtureOcrAdapter:
    """Return labeled synthetic ground truth only for an exact packaged fixture."""

    provider = "synthetic_fixture_fake"
    provider_version = OCR_FAKE_VERSION

    async def recognize(self, document: OcrDocument) -> OcrResult:
        key = document.fixture_key
        if key != "synthetic-scanned-specification.pdf":
            return self._unavailable()
        fixture = load_packaged_fixture(key)
        if document.attachment.original_bytes != fixture:
            return self._unavailable()
        pages = tuple(
            ParsedPage(page_number=index, text=text)
            for index, text in enumerate(SYNTHETIC_SCANNED_GROUND_TRUTH, 1)
        )
        text = "\n\n".join(page.text for page in pages)
        return OcrResult(
            provider=self.provider,
            provider_version=OCR_FAKE_VERSION,
            synthetic=True,
            pages=pages,
            extracted_text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            status="recognized",
        )

    def _unavailable(self) -> OcrResult:
        return OcrResult(
            provider=self.provider,
            provider_version=OCR_FAKE_VERSION,
            synthetic=True,
            pages=(),
            extracted_text="",
            text_sha256=None,
            status="unavailable",
        )
