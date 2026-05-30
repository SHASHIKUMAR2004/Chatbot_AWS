"""File upload endpoint: accepts a document, extracts its text and stores it
as an Attachment that will be injected into the conversation's LLM context."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import crud
from ..config import settings
from ..database import get_db
from ..extract import ExtractionError, extract_text, is_image, prepare_image
from ..schemas import AttachmentOut

logger = logging.getLogger("chatbot.files")
router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload", response_model=AttachmentOut)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a single document or image. Returns its attachment id.

    Text documents (PDF/DOCX/text) are extracted to text. Images are
    downscaled and stored as base64 for the vision path. Nothing is linked to
    a conversation yet — that happens on the first chat message referencing it.
    """
    raw = await file.read()
    size_mb = len(raw) / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large ({size_mb:.1f} MB). "
            f"Max is {settings.max_upload_mb} MB.",
        )

    filename = file.filename or "file"

    # --- Image path (vision) ---
    if is_image(filename):
        try:
            b64, mime = prepare_image(raw)
        except ExtractionError as exc:
            raise HTTPException(status_code=415, detail=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("Image processing failed")
            raise HTTPException(status_code=500, detail="Could not process this image.")
        att = crud.create_attachment(
            db, filename=filename, content=b64, kind="image", mime=mime
        )
        return att

    # --- Text document path ---
    try:
        text, truncated = extract_text(filename, raw)
    except ExtractionError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("Extraction failed")
        raise HTTPException(status_code=500, detail="Could not process this file.")

    att = crud.create_attachment(
        db, filename=filename, content=text, kind="text", truncated=truncated
    )
    return att