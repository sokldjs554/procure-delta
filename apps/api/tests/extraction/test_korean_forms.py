"""Exercise the real extractor/validator without database fixtures."""

import asyncio
from copy import deepcopy

import pytest

from app.extraction import service
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import DocumentBundle, DocumentPage, ExtractionResult
from app.extraction.validation import validate_extraction


def document(text: str) -> DocumentBundle:
    return DocumentBundle(
        pages=(
            DocumentPage(
                attachment_sha256="a" * 64,
                page_number=1,
                text=text,
                parser_kind="ocr",
                parser_version="test",
            ),
        )
    )


def extract(text: str):
    source = document(text)
    result = asyncio.run(DeterministicExtractor().extract(source))
    return source, result, validate_extraction(result, source)


@pytest.mark.parametrize(
    "title_line",
    [
        "ㆍ공 고 명 : 합성 시설 진단",
        "가. 용 역 명： 합성 시설 진단",
        "1) 입찰건명: 합성 시설 진단",
        "· 사업명 :\n합성 시설 진단",
    ],
)
def test_form_labels_preserve_exact_evidence(title_line):
    source, result, report = extract(
        f"용 역 입 찰 공 고\n{title_line}\nㆍ수 요 기 관 : 합성 교육청"
    )
    assert report.valid, report.errors
    assert report.fields.title == "합성 시설 진단"
    assert report.fields.buyer_name == "합성 교육청"
    assert report.fields.procurement_type == "services"
    assert result.output["evidence"]["title"][0]["quote"] == title_line
    forged = deepcopy(result.output)
    forged["evidence"]["title"][0]["quote"] = "공고명: 합성 시설 진단"
    assert not validate_extraction(ExtractionResult(output=forged), source).valid


@pytest.mark.parametrize(
    "heading,kind",
    [
        ("물 품 입 찰 공 고", "goods"),
        ("공사 입찰 설명서", "works"),
        ("용역 소액수의(견적제출) 설명서", "services"),
        ("조달물자(용역) 구매입찰 공고", "services"),
    ],
)
def test_category_requires_complete_notice_heading(heading, kind):
    _, _, report = extract(f"{heading}\n공고명: 합성 사업\n수요기관: 합성 기관")
    assert report.valid, report.errors
    assert report.fields.procurement_type == kind
    _, _, qualified = extract(f"{heading} 대상이 아님\n공고명: 합성 사업\n수요기관: 합성 기관")
    assert not qualified.valid


def test_normalized_negative_requirement_still_blocks_positive_claim():
    source, result, _ = extract(
        "공고명: 합성 사업\n수요기관: 합성 기관\n분류: 용역\n"
        "필수인증: ISO 27001\n나. 필 수 인 증：\nISO 27001 불필요"
    )
    report = validate_extraction(result, source)
    assert not report.valid
    assert any("negated" in error for error in report.errors)


def test_normalized_conflicting_claim_on_another_page_is_rejected():
    _, result, report = extract("Title: Original\nBuyer: Agency\nCategory: services")
    assert report.valid
    source = DocumentBundle(
        pages=(
            document("Title: Original\nBuyer: Agency\nCategory: services").pages[0],
            document("1. 공 고 명 : Other").pages[0].model_copy(update={"page_number": 2}),
        )
    )
    report = validate_extraction(result, source)
    assert not report.valid
    assert any("contradictory" in error for error in report.errors)


@pytest.mark.parametrize(
    "text",
    [
        "공고명:\n\n합성 사업\n수요기관: 합성 기관\n분류: 용역",
        "공고명:\n수요기관: 합성 기관\n분류: 용역",
        "공고명:\n1. 입찰 사항\n수요기관: 합성 기관\n분류: 용역",
        "합성 조달청 공고\n공고명: 합성 사업\n분류: 용역",
        "안내 문구 공고명: 합성 사업\n수요기관: 합성 기관\n분류: 용역",
    ],
)
def test_unbounded_or_unlabeled_values_remain_untrusted(text):
    assert not extract(text)[2].valid


def test_multiline_quote_cannot_skip_an_intervening_line():
    source, result, report = extract("공고명:\n합성 사업\n수요기관: 합성 기관\n분류: 용역")
    assert report.valid
    altered = source.pages[0].model_copy(
        update={"text": source.pages[0].text.replace("공고명:\n", "공고명:\n추가 설명\n")}
    )
    assert not validate_extraction(result, DocumentBundle(pages=(altered,))).valid


def test_grounding_policy_change_invalidates_completed_extraction_identity(monkeypatch):
    source = document("Title: Test\nBuyer: Test Agency\nCategory: services")
    extractor = DeterministicExtractor()
    original = service.extraction_identity(source, extractor)
    assert service.extraction_identity(source, extractor) == original
    monkeypatch.setattr(service, "GROUNDING_VERSION", "next-policy", raising=False)
    assert service.extraction_identity(source, extractor) != original


def test_label_normalization_does_not_rewrite_punctuation_inside_a_value():
    _, _, report = extract("Title: 합성：진단\nBuyer: Agency\nCategory: services")
    assert report.valid
    assert report.fields.title == "합성：진단"


def test_bare_english_label_is_not_consumed_as_adjacent_value():
    _, _, report = extract("Title:\nBuyer\nBuyer: Agency\nCategory: services")
    assert not report.valid


@pytest.mark.parametrize(
    "section",
    [
        "(1) 입찰 사항",
        "① 입찰 사항",
        "Ⅰ. 입찰 사항",
        "[입찰 사항]",
        "A. 입찰 사항",
        "II. 입찰 사항",
        "1.1 입찰 사항",
        "※ 입찰 사항",
    ],
)
def test_adjacent_section_markers_are_not_a_title(section):
    _, _, report = extract(f"공고명:\n{section}\n수요기관: 합성 기관\n분류: 용역")
    assert not report.valid
