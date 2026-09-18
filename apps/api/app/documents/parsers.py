from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser

import pymupdf

from app.documents.download import StoredAttachment

PARSER_VERSION = "native-v1"


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    checksum: str
    parser_kind: str
    parser_version: str
    pages: tuple[ParsedPage, ...]
    page_count: int
    extracted_text: str
    text_sha256: str
    status: str


class _VisibleHTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth and data.strip():
            self.parts.append(data.strip())


def _result(
    attachment: StoredAttachment,
    parser_kind: str,
    pages: tuple[ParsedPage, ...],
    status: str,
) -> ParsedDocument:
    text = "\n\n".join(page.text for page in pages)
    return ParsedDocument(
        checksum=attachment.sha256,
        parser_kind=parser_kind,
        parser_version=PARSER_VERSION,
        pages=pages,
        page_count=len(pages),
        extracted_text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        status=status,
    )


def parse_document(attachment: StoredAttachment) -> ParsedDocument:
    """Parse supported native formats without executing embedded document content."""
    if attachment.media_type == "application/pdf":
        with pymupdf.open(  # type: ignore[no-untyped-call]
            stream=attachment.original_bytes, filetype="pdf"
        ) as document:
            pages = tuple(
                ParsedPage(page_number=index + 1, text=page.get_text("text"))
                for index, page in enumerate(document)
            )
        return _result(attachment, "native_pdf", pages, "parsed")
    if attachment.media_type in {"text/html", "application/xhtml+xml"}:
        parser = _VisibleHTMLText()
        parser.feed(attachment.original_bytes.decode("utf-8", errors="replace"))
        return _result(
            attachment,
            "html",
            (ParsedPage(page_number=1, text="\n".join(parser.parts)),),
            "parsed",
        )
    if attachment.media_type in {"application/x-hwp", "application/haansofthwp"}:
        return _result(attachment, "hwp_adapter", (), "unsupported")
    return _result(attachment, "unsupported", (), "unsupported")
