from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import IngestResponse
from app.stages.stage1_ingest import ingest_csv

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile, db: Session = Depends(get_db)) -> IngestResponse:
    file_bytes = await file.read()
    result = ingest_csv(db, file_bytes)
    return IngestResponse(ingested=result.ingested, rejected=result.rejected)
