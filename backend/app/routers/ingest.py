from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import IngestResponse
from app.stages.pipeline_runner import qualify_and_launch_pipeline
from app.stages.stage1_ingest import ingest_csv

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> IngestResponse:
    """Upload is the only manual step in the workflow: qualify, research, and
    email generation all kick off automatically from here (see
    app/stages/pipeline_runner.py::qualify_and_launch_pipeline). Sending an
    email stays a separate, explicit, human-triggered action."""
    file_bytes = await file.read()
    result = ingest_csv(db, file_bytes)

    settings = get_settings()
    pipeline_result = qualify_and_launch_pipeline(
        db,
        background_tasks,
        batch_cap=settings.QUALIFY_BATCH_CAP,
    )

    return IngestResponse(
        ingested=result.ingested,
        rejected=result.rejected,
        qualified_count=len(pipeline_result.qualified_ids),
        disqualified_count=pipeline_result.disqualified_count,
        pipeline_started_count=len(pipeline_result.qualified_ids),
    )
