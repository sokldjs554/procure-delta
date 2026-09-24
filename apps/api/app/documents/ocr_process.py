"""Private Linux OCR child. Document bytes/text never appear in errors or logs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
from pathlib import Path
from typing import Any

import pymupdf

from app.documents.ocr_runtime import (
    MAX_INPUT_BYTES,
    MAX_TEXT_CHARS,
    PROCESS_MEMORY_BYTES,
    RUNTIME_ADAPTER_VERSION,
    RuntimeOcrConfig,
)


def runtime_identity(config: RuntimeOcrConfig) -> str:
    models = {}
    for language in config.language.split("+"):
        path = config.tessdata_dir / f"{language}.traineddata"
        if not path.is_file():
            raise ValueError("missing_language_data")
        with path.open("rb") as model:
            models[language] = hashlib.file_digest(model, "sha256").hexdigest()
    contract = {
        "adapter": RUNTIME_ADAPTER_VERSION, "pymupdf": pymupdf.VersionBind,
        "mupdf": pymupdf.VersionFitz, "models": models,
        "config": config.model_dump(mode="json", exclude={"tessdata_dir"}),
        "memory_bytes": PROCESS_MEMORY_BYTES, "text_chars": MAX_TEXT_CHARS,
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


def recognize(config: RuntimeOcrConfig, path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input_limit")
    with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
        if not document.is_pdf or document.needs_pass:
            raise ValueError("unsupported_pdf")
        if not 1 <= document.page_count <= config.max_pages:
            raise ValueError("page_limit")
        # Inspect every page before recognizing any: no partial successful result.
        for page in document:
            width = math.ceil(page.rect.width * config.dpi / 72)
            height = math.ceil(page.rect.height * config.dpi / 72)
            if width < 1 or height < 1 or width * height > config.max_pixels_per_page:
                raise ValueError("pixel_limit")
        pages = []
        total = 0
        for index, page in enumerate(document, 1):
            # Prior decoded scanner images can exhaust this child's address-space
            # limit before MuPDF's cache evicts them. Each page starts without
            # cached resources; resolution, models and process limits stay fixed.
            pymupdf.TOOLS.store_shrink(100)  # type: ignore[no-untyped-call]
            textpage = page.get_textpage_ocr(
                language=config.language, dpi=config.dpi, full=True,
                tessdata=str(config.tessdata_dir),
            )
            text = str(textpage.extractText()).strip()
            # Do not retain the prior native TextPage while allocating the next.
            del textpage
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise ValueError("runtime_failed")
            pages.append({"page_number": index, "text": text})
        return pages


def probe(config: RuntimeOcrConfig) -> None:
    # Exercise the integrated engine, not just the existence of model filenames.
    with pymupdf.open() as document:  # type: ignore[no-untyped-call]
        page = document.new_page(width=500, height=150)
        page.insert_text((30, 60), "Runtime OCR probe", fontsize=24)
        text = page.get_textpage_ocr(language=config.language, dpi=150, full=True,
                                     tessdata=str(config.tessdata_dir)).extractText()
        if not str(text).strip():
            raise ValueError("runtime_failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    result: dict[str, Any]
    try:
        config = RuntimeOcrConfig.model_validate_json(args.config)
        resource.setrlimit(resource.RLIMIT_AS, (PROCESS_MEMORY_BYTES, PROCESS_MEMORY_BYTES))
        cpu = math.ceil(config.timeout_seconds) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        identity = runtime_identity(config)
        if args.probe:
            probe(config)
            result = {"identity": identity}
        else:
            result = {"identity": identity, "pages": recognize(config, args.pdf)}
    except Exception as error:
        allowed = {"page_limit", "pixel_limit", "input_limit", "unsupported_pdf",
                   "missing_language_data"}
        code = (str(error) if type(error) is ValueError and str(error) in allowed
                else "runtime_failed")
        result = {"error": code}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
