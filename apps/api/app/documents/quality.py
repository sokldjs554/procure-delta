from __future__ import annotations

from dataclasses import dataclass

from app.documents.parsers import ParsedDocument


@dataclass(frozen=True, slots=True)
class PageTextQuality:
    page_number: int
    char_count: int
    non_whitespace_chars: int
    printable_ratio: float
    alphanumeric_ratio: float
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextQuality:
    char_count: int
    non_whitespace_chars: int
    printable_ratio: float
    alphanumeric_ratio: float
    status: str
    reasons: tuple[str, ...]
    page_signals: tuple[PageTextQuality, ...]


def _signals(text: str, page_number: int) -> PageTextQuality:
    chars = len(text)
    non_whitespace = sum(not char.isspace() for char in text)
    printable = sum(char.isprintable() or char.isspace() for char in text)
    alphanumeric = sum(char.isalnum() for char in text)
    printable_ratio = printable / chars if chars else 0.0
    alphanumeric_ratio = alphanumeric / non_whitespace if non_whitespace else 0.0
    reasons: list[str] = []
    if non_whitespace == 0:
        reasons.append("empty_text")
    elif non_whitespace < 20:
        reasons.append("too_little_text")
    if chars and printable_ratio < 0.9:
        reasons.append("low_printable_ratio")
    if non_whitespace and alphanumeric_ratio < 0.5:
        reasons.append("low_alphanumeric_ratio")
    return PageTextQuality(
        page_number=page_number,
        char_count=chars,
        non_whitespace_chars=non_whitespace,
        printable_ratio=round(printable_ratio, 6),
        alphanumeric_ratio=round(alphanumeric_ratio, 6),
        status="needs_ocr" if reasons else "trusted",
        reasons=tuple(reasons),
    )


def assess_page_quality(text: str, page_number: int) -> PageTextQuality:
    """Reassess stored legacy pages with the same native/OCR page-quality rules."""
    return _signals(text, page_number)


def assess_text_quality(parsed: ParsedDocument) -> TextQuality:
    """Decide whether native text is usable; structured trust remains a later gate."""
    text = parsed.extracted_text
    aggregate = _signals(text, 0)
    page_signals = tuple(_signals(page.text, page.page_number) for page in parsed.pages)
    if parsed.status == "unsupported":
        return TextQuality(
            aggregate.char_count,
            aggregate.non_whitespace_chars,
            aggregate.printable_ratio,
            aggregate.alphanumeric_ratio,
            "unsupported",
            ("unsupported_format",),
            page_signals,
        )
    reasons = list(aggregate.reasons)
    for page in page_signals:
        reasons.extend(f"page_{page.page_number}:{reason}" for reason in page.reasons)
    return TextQuality(
        char_count=aggregate.char_count,
        non_whitespace_chars=aggregate.non_whitespace_chars,
        printable_ratio=aggregate.printable_ratio,
        alphanumeric_ratio=aggregate.alphanumeric_ratio,
        status="needs_ocr" if reasons else "trusted",
        reasons=tuple(reasons),
        page_signals=page_signals,
    )
