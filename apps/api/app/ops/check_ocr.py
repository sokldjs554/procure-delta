"""Exercise configured real OCR in the deployed image without document output."""
from __future__ import annotations

import asyncio
import json

from app.config import get_settings
from app.documents.ocr_runtime import configured_ocr_adapter


async def check() -> dict[str, object]:
    settings = get_settings()
    if settings.ocr_backend != "tesseract":
        raise RuntimeError("OCR_BACKEND=tesseract is required for the runtime probe")
    adapter = await configured_ocr_adapter(settings)
    return {"ready": True, "provider": adapter.provider,
            "provider_version": adapter.provider_version,
            "scope": "startup_engine_probe", "quality_evaluated": False}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(check())))
