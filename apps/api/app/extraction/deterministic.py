from typing import Any

from app.extraction.schemas import DocumentBundle, ExtractionResult
from app.extraction.validation import labeled_claims


class DeterministicExtractor:
    """Local/demo extraction of explicit labels, with no inference from raw records."""

    extractor_version = "deterministic-labels-v1"
    provider = "local"
    model = "labeled-text-v1"

    async def extract(self, document: DocumentBundle) -> ExtractionResult:
        output: dict[str, Any] = {"schema_version": "1", "evidence": {}}
        for page in document.pages:
            for line in page.text.splitlines():
                for field, value in labeled_claims(line).items():
                    output.setdefault(field, value)
                    output["evidence"].setdefault(field, []).append(
                        {
                            "attachment_sha256": page.attachment_sha256,
                            "page_number": page.page_number,
                            "quote": line.strip(),
                        }
                    )
        # The persisted proposal must remain JSON serializable even when rejected.
        from pydantic_core import to_jsonable_python

        return ExtractionResult(output=to_jsonable_python(output))
