"""Conversation management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_all(db: Session = Depends(get_db)):
    return crud.list_conversations(db)


@router.post("", response_model=ConversationOut, status_code=201)
def create(payload: ConversationCreate, db: Session = Depends(get_db)):
    return crud.create_conversation(db, title=payload.title, model=payload.model)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_one(conversation_id: str, db: Session = Depends(get_db)):
    convo = crud.get_conversation(db, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename(
    conversation_id: str,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
):
    convo = crud.rename_conversation(db, conversation_id, payload.title)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo


@router.delete("/{conversation_id}", status_code=204)
def delete_one(conversation_id: str, db: Session = Depends(get_db)):
    if not crud.delete_conversation(db, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.delete("", status_code=200)
def delete_all(db: Session = Depends(get_db)):
    count = crud.delete_all_conversations(db)
    return {"deleted": count}
