"""File upload endpoint: accepts a document, extracts its text and stores it
as an Attachment that will be injected into the conversation's LLM context."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import crud
from ..config import settings
from ..database import get_db
from ..extract import ExtractionError, extract_text
from ..schemas import AttachmentOut

logger = logging.getLogger("chatbot.files")
router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload", response_model=AttachmentOut)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a single document. Returns its attachment id + char count.

    The file is not linked to a conversation yet — that happens on the first
    chat message that references the returned id.
    """
    raw = await file.read()
    size_mb = len(raw) / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large ({size_mb:.1f} MB). "
            f"Max is {settings.max_upload_mb} MB.",
        )

    try:
        text, truncated = extract_text(file.filename or "file", raw)
    except ExtractionError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Extraction failed")
        raise HTTPException(status_code=500, detail="Could not process this file.")

    att = crud.create_attachment(
        db,
        filename=file.filename or "file",
        content=text,
        truncated=truncated,
    )
    return att
