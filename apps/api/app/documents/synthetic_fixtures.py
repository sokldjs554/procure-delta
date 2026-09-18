from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pymupdf

SYNTHETIC_SCANNED_GROUND_TRUTH = (
    """SYNTHETIC PROCUREMENT NOTICE
Title: Synthetic Secure Cloud Operations Platform
Buyer: Synthetic Seoul Digital Agency
Category: IT services
Budget: KRW 125,000,000
Published: 2026-09-03
Deadline: 2026-09-30 18:00 KST""",
    """Region: Seoul
Certifications: ISO 27001; GS certification
Capabilities: cloud migration; security monitoring; incident response
Contract period: 2026-10-15 to 2027-04-14
Participation constraints: Synthetic SMEs registered for software services only
Fixture label: Synthetic data for local and CI testing""",
)


@lru_cache(maxsize=1)
def _synthetic_pdf() -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    first = document.new_page()
    first.insert_text((72, 72), "Synthetic PDF procurement notice - Page 1")
    second = document.new_page()
    second.insert_text((72, 72), "Synthetic PDF evidence - Page 2")
    # Suppress MuPDF's generated trailer ID so the fixture checksum survives restarts.
    content: bytes = document.tobytes(no_new_id=True)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return content


@lru_cache(maxsize=1)
def _synthetic_scanned_pdf() -> bytes:
    source = pymupdf.open()  # type: ignore[no-untyped-call]
    for page_text in SYNTHETIC_SCANNED_GROUND_TRUTH:
        page = source.new_page(width=595, height=842)
        page.insert_textbox(
            pymupdf.Rect(54, 54, 541, 788),  # type: ignore[no-untyped-call]
            page_text,
            fontsize=12,
            fontname="cour",
            lineheight=1.4,
        )
    scanned = pymupdf.open()  # type: ignore[no-untyped-call]
    for page_number in range(source.page_count):
        page = source[page_number]
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),  # type: ignore[no-untyped-call]
            alpha=False,
        )
        scanned_page = scanned.new_page(width=595, height=842)
        scanned_page.insert_image(  # type: ignore[no-untyped-call]
            scanned_page.rect, pixmap=pixmap
        )
    content: bytes = scanned.tobytes(no_new_id=True, deflate=True)  # type: ignore[no-untyped-call]
    scanned.close()  # type: ignore[no-untyped-call]
    source.close()  # type: ignore[no-untyped-call]
    return content


@lru_cache(maxsize=1)
def _synthetic_garbled_pdf() -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text((72, 72), "!@#$%^&*()[]{}<>?/\\|~`_-+=")
    content: bytes = document.tobytes(no_new_id=True)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return content


def load_packaged_fixture(key: str) -> bytes:
    """Resolve application-owned deterministic fixtures, never caller paths."""
    if key.startswith("lifecycle-demo:"):
        from app.demo.dataset import resolve_demo_fixture

        return resolve_demo_fixture(key)
    if key == "synthetic-specification.pdf":
        return _synthetic_pdf()
    if key == "synthetic-scanned-specification.pdf":
        return _synthetic_scanned_pdf()
    if key == "synthetic-garbled.pdf":
        return _synthetic_garbled_pdf()
    if key in {"synthetic-specification.html", "synthetic-tender-details-v2.html", "corrupt.pdf"}:
        return (Path(__file__).with_name("fixtures") / key).read_bytes()
    raise ValueError("unknown packaged attachment fixture")
