"""Pydantic schemas for request validation and API responses."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- Chat ----------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    attachment_ids: List[str] = Field(default_factory=list)


# ---------- Attachments ----------
class AttachmentOut(BaseModel):
    id: str
    filename: str
    kind: str = "text"
    chars: int
    truncated: bool = False

    model_config = {"from_attributes": True}


# Legacy non-streaming response (keeps backward compatibility with v1 clients)
class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    model: str


# ---------- Messages ----------
class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    model: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- Conversations ----------
class ConversationCreate(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationOut):
    messages: List[MessageOut] = []


# ---------- Models ----------
class ModelInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    is_default: bool = False