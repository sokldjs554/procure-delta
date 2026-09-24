from pathlib import Path

from fastapi import APIRouter

from app.evaluation.summary import EvaluationSummary, read_published_summary

router = APIRouter(prefix='/api/v1/evaluation', tags=['evaluation'])


@router.get('/summary', response_model=EvaluationSummary)
def summary() -> EvaluationSummary:
    results = Path(__file__).resolve().parents[1] / "evaluation/results"
    return read_published_summary(results)
