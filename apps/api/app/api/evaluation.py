from pathlib import Path

from fastapi import APIRouter

from app.evaluation.summary import EvaluationSummary, read_korean_ocr_route, read_summary

router = APIRouter(prefix='/api/v1/evaluation', tags=['evaluation'])


@router.get('/summary', response_model=EvaluationSummary)
def summary() -> EvaluationSummary:
    results = Path(__file__).resolve().parents[1] / "evaluation/results"
    result = read_summary(results / "local.json")
    result.routes["ocr_korean"] = read_korean_ocr_route(results / "korean-ocr.json")
    return result
