"""Measured Korean OCR regression using generated synthetic procurement text."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"),
)
SOURCE_TEXT = (
    "사업명: 합성 클라우드 전환 사업\n"
    "발주기관: 예시 공공기관\n"
    "분류: 용역\n"
    "예산: 125,000,000원\n"
    "지역: 서울"
)
EXPECTED_FIELDS = {
    "title": "합성 클라우드 전환 사업",
    "buyer_name": "예시 공공기관",
    "procurement_type": "services",
    "estimated_amount": "125000000",
    "currency": "KRW",
    "regions": ["서울"],
}


def _font_path() -> Path:
    for path in FONT_CANDIDATES:
        if path.is_file():
            return path
    raise RuntimeError("Korean OCR regression requires a committed CI font package")


def generate_suite(directory: Path) -> dict[str, object]:
    font_path = _font_path()
    font = ImageFont.truetype(str(font_path), 36)
    image = Image.new("L", (1300, 450), 255)
    ImageDraw.Draw(image).multiline_text(
        (45, 45),
        SOURCE_TEXT,
        font=font,
        fill=0,
        spacing=18,
    )
    variants = {
        "clean": image,
        "blurred": image.filter(ImageFilter.GaussianBlur(1.2)),
        "low_resolution": image.resize((520, 180)).resize(image.size),
    }
    target = directory / "ocr_ko"
    target.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, object]] = []
    image_sha256: dict[str, str] = {}
    for name, variant in variants.items():
        path = target / f"{name}.png"
        variant.save(path)
        relative = path.relative_to(directory).as_posix()
        image_sha256[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        cases.append(
            {
                "id": f"ko_{name}",
                "path": relative,
                "expected_fields": EXPECTED_FIELDS,
                "language": "kor+eng",
                "synthetic": True,
            }
        )
    manifest = {
        "suite_version": "korean-synthetic-v1",
        "cases": cases,
        "source_text": SOURCE_TEXT,
        "source_text_sha256": hashlib.sha256(SOURCE_TEXT.encode("utf-8")).hexdigest(),
        "font": font_path.name,
        "image_sha256": image_sha256,
        "synthetic": True,
    }
    (directory / "ocr_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


async def run(output: Path) -> dict[str, object]:
    from app.evaluation.ocr import evaluate_ocr

    with tempfile.TemporaryDirectory(prefix="procure-delta-korean-ocr-") as temporary:
        directory = Path(temporary)
        manifest = generate_suite(directory)
        measured = await evaluate_ocr(directory)
    result: dict[str, object] = {
        "schema_version": 1,
        "suite": manifest["suite_version"],
        "synthetic": True,
        "source_text_sha256": manifest["source_text_sha256"],
        "font": manifest["font"],
        "image_sha256": manifest["image_sha256"],
        "measurement": measured,
        "limitation": (
            "Synthetic Korean rendered text only; not production scans, handwriting, "
            "tables, or diverse public-procurement document layouts."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/evaluation/korean-ocr.json",
    )
    args = parser.parse_args()
    result = asyncio.run(run(args.output))
    measurement = result["measurement"]
    if not isinstance(measurement, dict) or measurement.get("status") != "measured":
        raise SystemExit("Korean OCR regression was not measured")
    if measurement.get("expected_fields") != 18 or measurement.get("correct_fields") != 18:
        raise SystemExit(
            "Korean OCR regression failed: expected 18/18 structured fields"
        )
    if measurement.get("field_accuracy") != 1.0:
        raise SystemExit("Korean OCR regression failed: field accuracy must be 1.0")
    print(f"Korean OCR artifact: {args.output}")
    print(
        "field_accuracy="
        f"{measurement.get('field_accuracy')} "
        f"support={measurement.get('expected_fields')} "
        f"language={measurement.get('language')}"
    )


if __name__ == "__main__":
    main()
