from typing import Protocol

from app.extraction.schemas import DocumentBundle, ExtractionResult


class StructuredExtractor(Protocol):
    extractor_version: str
    provider: str
    model: str

    async def extract(self, document: DocumentBundle) -> ExtractionResult: ...
