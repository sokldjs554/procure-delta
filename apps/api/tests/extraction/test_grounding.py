import pytest

from app.documents.synthetic_fixtures import SYNTHETIC_SCANNED_GROUND_TRUTH
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import DocumentBundle, DocumentPage
from app.extraction.validation import validate_extraction
from tests.extraction.test_schema_validation import bundle, proposal


@pytest.mark.parametrize(
    ("field", "value", "quote", "text"),
    [
        ("title", "Invented", "Title: Real", "Title: Real"),
        ("buyer_name", "Real", "Title: Real", "Title: Real"),
        (
            "required_capabilities",
            ["cloud", "invented"],
            "Capabilities: cloud",
            "Capabilities: cloud",
        ),
        (
            "required_certifications",
            ["ISO 27001"],
            "Certifications: not ISO 27001",
            "Certifications: not ISO 27001",
        ),
        ("estimated_amount", "100", "Title: 100", "Title: 100"),
        ("title", "Real", "Title: Real", "Title: Other"),
    ],
)
def test_claim_must_match_the_correct_labeled_source(field, value, quote, text):
    report = validate_extraction(proposal(field, value, quote), bundle(text))
    assert not report.valid
    assert any(error.startswith(field + ":") for error in report.errors)


@pytest.mark.parametrize("key,value", [("attachment_sha256", "b" * 64), ("page_number", 2)])
def test_wrong_provenance_rejected(key, value):
    result = proposal("title", "Real", "Title: Real")
    result.output["evidence"]["title"][0][key] = value
    assert not validate_extraction(result, bundle("Title: Real")).valid


@pytest.mark.asyncio
async def test_deterministic_scanned_fixture_grounded() -> None:
    document = DocumentBundle(
        pages=tuple(
            DocumentPage(
                attachment_sha256="a" * 64,
                page_number=index,
                text=text,
                parser_kind="ocr",
                parser_version="fixture-v1",
            )
            for index, text in enumerate(SYNTHETIC_SCANNED_GROUND_TRUTH, 1)
        )
    )
    result = await DeterministicExtractor().extract(document)
    report = validate_extraction(result, document)
    assert report.valid, report.errors
    assert report.fields.estimated_amount == 125000000
    assert report.fields.regions == ["Seoul"]
    assert report.fields.required_capabilities == [
        "cloud migration",
        "security monitoring",
        "incident response",
    ]
    assert result.prompt_tokens is None


@pytest.mark.asyncio
async def test_korean_labeled_procurement_notice() -> None:
    document = DocumentBundle(
        pages=(
            DocumentPage(
                attachment_sha256="c" * 64,
                page_number=1,
                parser_kind="native_html",
                parser_version="1",
                text="""합성 공고 (테스트 전용)
공고명: 합성 보안 시스템 구축
수요기관: 합성 서울 기관
분류: 용역
예산: 125,000,000원
공고일: 2026-09-03
마감일: 2026-09-30 18:00 KST
지역: 서울
필수인증: ISO 27001
필수역량: 클라우드 이전; 보안 모니터링
참가자격: 합성 중소기업
계약기간: 2026-10-15 to 2027-04-14""",
            ),
        )
    )
    result = await DeterministicExtractor().extract(document)
    report = validate_extraction(result, document)
    assert report.valid, report.errors
    assert report.fields.buyer_name == "합성 서울 기관"
    assert report.fields.estimated_amount == 125000000
    assert report.fields.currency == "KRW"
    assert report.fields.regions == ["서울"]


@pytest.mark.asyncio
async def test_contradictory_attachments_fail_closed() -> None:
    document = bundle("Title: Real\nTitle: Other")
    result = await DeterministicExtractor().extract(document)
    report = validate_extraction(result, document)
    assert not report.valid
    assert any("contradictory" in error for error in report.errors)


def test_negated_requirement_elsewhere_prevents_trusted_positive_claim() -> None:
    result = proposal("required_certifications", ["ISO 27001"], "Certifications: ISO 27001")
    document = bundle("Certifications: ISO 27001\nCertifications: not ISO 27001")
    report = validate_extraction(result, document)
    assert not report.valid
    assert any("negated" in error for error in report.errors)
