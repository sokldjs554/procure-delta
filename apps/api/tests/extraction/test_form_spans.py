"""Evidence remains exact when decoding bounded Korean form typography."""

from copy import deepcopy

import pytest

from app.extraction.schemas import DocumentBundle, ExtractionResult
from app.extraction.validation import validate_extraction
from tests.extraction.test_korean_forms import document, extract


@pytest.mark.parametrize(
    "heading,kind",
    [
        ("용역 소액수의[견적제출] 설명서", "services"),
        ("공사 소액수의（견적제출） 설명서", "works"),
        ("물품 소액수의［견적제출］ 설명서", "goods"),
        ("조달물자[용역] 구매입찰공고", "services"),
        ("조달물자（물품） 구매입찰공고", "goods"),
        ("용 역\n입 찰 공 고", "services"),
        ("용역 소액수의[견적제출]\r\n 설명서", "services"),
    ],
)
def test_complete_heading_typography_has_exact_source_evidence(heading, kind):
    source, result, report = extract(f"{heading}\n공고명: 합성 진단\n수요기관: 합성 기관")
    assert report.valid, report.errors
    assert report.fields.procurement_type == kind
    reference = result.output["evidence"]["procurement_type"][0]
    assert reference["quote"] == heading
    forged = deepcopy(result.output)
    forged["evidence"]["procurement_type"][0]["quote"] = heading + " "
    assert not validate_extraction(ExtractionResult(output=forged), source).valid


@pytest.mark.parametrize(
    "heading",
    [
        "용역 소액수의(견적제출] 설명서",
        "조달물자[용역） 구매입찰공고",
        "용역 소액수의[견적제출] 설명서 대상 아님",
        "용역\n입찰공고 대상 아님",
        "용역\n\n입찰공고",
        "용역\n추가 안내\n입찰공고",
        "용역\n입찰\n공고",
        "용역범위",
    ],
)
def test_ambiguous_or_incomplete_headings_do_not_supply_category(heading):
    assert not extract(f"{heading}\n공고명: 합성 진단\n수요기관: 합성 기관")[2].valid


def test_heading_must_not_cross_a_page():
    _, result, report = extract("용역\n입찰공고\n공고명: 합성 진단\n수요기관: 합성 기관")
    assert report.valid
    source = DocumentBundle(pages=(
        document("용역").pages[0],
        document("입찰공고\n공고명: 합성 진단\n수요기관: 합성 기관").pages[0].model_copy(
            update={"page_number": 2},
        ),
    ))
    assert not validate_extraction(result, source).valid


def test_wrapped_heading_contradiction_is_not_hidden_by_another_category():
    assert not extract(
        "분류: 물품\n용역\n입찰공고\n공고명: 합성 진단\n수요기관: 합성 기관"
    )[2].valid


def test_empty_title_cannot_consume_the_start_of_a_wrapped_category_heading():
    assert not extract("공고명:\n용역\n입찰공고\n수요기관: 합성 기관")[2].valid


@pytest.mark.parametrize(
    "source_value,expected",
    [
        ("「합성 시설 진단」", "합성 시설 진단"),
        ("[합성 시설 진단]", "합성 시설 진단"),
        ("“합성 시설 진단”", "합성 시설 진단"),
        ("\"합성 시설 진단\"", "합성 시설 진단"),
        ("「합성 시설\n  진단」", "합성 시설 진단"),
        ("「합성 「재공고」 시설 진단」", "합성 「재공고」 시설 진단"),
        ("「합성 「재공고」\n 시설 진단」", "합성 「재공고」 시설 진단"),
        ("[합성 [재공고] 시설 진단]", "합성 [재공고] 시설 진단"),
        ("[합성 [재공고]\n 시설 진단]", "합성 [재공고] 시설 진단"),
        ("[재공고] 합성 시설 진단", "[재공고] 합성 시설 진단"),
        ("합성 [시설] 진단", "합성 [시설] 진단"),
    ],
)
def test_title_enclosure_is_decoded_without_rewriting_evidence(source_value, expected):
    title = "입찰건명: " + source_value
    source, result, report = extract(title + "\n수요기관: 합성 기관\n분류: 용역")
    assert report.valid, report.errors
    assert report.fields.title == expected
    assert result.output["evidence"]["title"][0]["quote"] == title
    forged = deepcopy(result.output)
    forged["title"] = "다른 사업"
    assert not validate_extraction(ExtractionResult(output=forged), source).valid


@pytest.mark.parametrize(
    "title",
    [
        "입찰건명: 「합성 시설\n\n진단」",
        "입찰건명: 「합성 시설\n1. 입찰 사항」",
        "입찰건명: 「합성 시설\n분류: 용역」",
        "입찰건명: 「합성 시설\n진단\n용역」",
        "입찰건명: 「합성 시설]",
        "입찰건명: []",
        "입찰건명: 「" + "가" * 301 + "\n진단」",
        "입찰건명: 「합성 「재공고」",
        "입찰건명: [합성 [재공고]\n 시설\n 진단]",
        "입찰건명: 「합성 「재공고」\n\n 시설 진단」",
        "입찰건명: [합성 [재공고]\n1. 시설 진단]",
    ],
)
def test_unbounded_or_malformed_quoted_titles_fail_closed(title):
    assert not extract(title + "\n수요기관: 합성 기관\n분류: 용역")[2].valid


def test_broken_quoted_title_elsewhere_is_not_silently_discarded():
    assert not extract(
        "공고명: 합성 진단\n공고명: 「다른 사업\n수요기관: 합성 기관\n분류: 용역"
    )[2].valid


@pytest.mark.parametrize("period", ["계약일로부터 과업 종료까지", "계약일로부터~'26.12.중순"])
def test_relative_optional_contract_period_is_omitted_without_guessing_dates(period):
    source, result, report = extract(
        "공고명: 합성 진단\n수요기관: 합성 기관\n분류: 용역\n계약기간: " + period
    )
    assert report.valid, report.errors
    assert "contract_period" not in result.output
    assert "contract_period" not in result.output["evidence"]
    forged = deepcopy(result.output)
    forged["contract_period"] = "2026-01-01/2026-12-31"
    forged["evidence"]["contract_period"] = [{
        "attachment_sha256": source.pages[0].attachment_sha256,
        "page_number": 1, "quote": "계약기간: " + period,
    }]
    assert not validate_extraction(ExtractionResult(output=forged), source).valid


@pytest.mark.parametrize("period", ["2026-12-31 to 2026-01-01", "2026-02-30/2026-12-31"])
def test_invalid_explicit_contract_dates_are_rejected_not_omitted(period):
    _, result, report = extract(
        "공고명: 합성 진단\n수요기관: 합성 기관\n분류: 용역\n계약기간: " + period
    )
    assert "contract_period" in result.output
    assert not report.valid
