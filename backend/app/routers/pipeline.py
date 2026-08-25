"""POST /api/pipeline/run-batch.

Convenience endpoint: runs Stage 2 qualify synchronously (it's cheap, plain
Python, no LLM), then kicks off Stage 3->4->5 for each newly-qualified
prospect as a background task. Best-effort: if ANTHROPIC_API_KEY isn't set,
qualify still runs, but the per-prospect background jobs no-op immediately
(prospects stay at QUALIFIED for a manual /research call once a key is set)
rather than returning an error, since qualify itself succeeded.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import PipelineRunBatchRequest, RunBatchResponse
from app.stages.pipeline_runner import run_full_pipeline_for_prospect
from app.stages.stage2_qualify import qualify_batch

router = APIRouter(tags=["pipeline"])


@router.post("/pipeline/run-batch", response_model=RunBatchResponse)
def run_batch(
    background_tasks: BackgroundTasks,
    _body: PipelineRunBatchRequest = PipelineRunBatchRequest(),
    db: Session = Depends(get_db),
) -> RunBatchResponse:
    settings = get_settings()
    result = qualify_batch(
        db,
        batch_cap=settings.QUALIFY_BATCH_CAP,
        headcount_min=settings.QUALIFY_HEADCOUNT_MIN,
        headcount_max=settings.QUALIFY_HEADCOUNT_MAX,
    )

    for prospect_id in result.qualified_ids:
        background_tasks.add_task(run_full_pipeline_for_prospect, prospect_id)

    return RunBatchResponse(started=len(result.qualified_ids) > 0)
