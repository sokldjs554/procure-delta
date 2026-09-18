from pathlib import Path

from fastapi import APIRouter

from app.evaluation.summary import EvaluationSummary, read_summary

router = APIRouter(prefix='/api/v1/evaluation', tags=['evaluation'])


@router.get('/summary', response_model=EvaluationSummary)
def summary() -> EvaluationSummary:
    artifact = Path(__file__).resolve().parents[1] / 'evaluation/results/local.json'
    return read_summary(artifact)
