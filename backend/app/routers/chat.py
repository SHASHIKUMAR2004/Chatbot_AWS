"""Chat endpoints: streaming (SSE) + legacy non-streaming + model listing."""
from __future__ import annotations

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import crud, llm
from ..config import settings
from ..database import SessionLocal, get_db
from ..schemas import ChatRequest, ChatResponse, ModelInfo

logger = logging.getLogger("chatbot.chat")
router = APIRouter(prefix="/api", tags=["chat"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_messages(db: Session, conversation_id: str, system_prompt: str | None):
    system = system_prompt or settings.effective_system_prompt
    msgs = [{"role": "system", "content": system}]
    # Inject any attached-document text as a second system message.
    doc_context = crud.build_document_context(db, conversation_id)
    if doc_context:
        msgs.append({"role": "system", "content": doc_context})
    msgs.extend(crud.history_for_llm(db, conversation_id))

    # Attach images (if any) to the most recent user message as image_url parts
    # so a vision model can see them.
    images = crud.image_attachments_for_conversation(
        db, conversation_id, settings.max_images_per_request
    )
    if images:
        for m in reversed(msgs):
            if m["role"] == "user":
                parts = [{"type": "text", "text": m["content"]}]
                for img in images:
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{img.mime or 'image/jpeg'};base64,{img.content}"
                            },
                        }
                    )
                m["content"] = parts
                break
    return msgs, bool(images)


def _resolve_model(requested: str | None, has_images: bool) -> str:
    """Pick the model to call. Force a vision model when images are present."""
    model = requested or settings.default_model
    if has_images and not llm.is_vision_model(model):
        return settings.vision_model
    return model


@router.get("/models", response_model=list[ModelInfo])
def get_models():
    return llm.list_models()


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    """Stream a model response as Server-Sent Events.

    Event types: `meta`, `delta`, `done`, `error`.
    """
    model = payload.model or settings.default_model

    # Resolve or create the conversation.
    convo = None
    if payload.conversation_id:
        convo = crud.get_conversation(db, payload.conversation_id)
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    is_new = convo is None
    if convo is None:
        convo = crud.create_conversation(
            db, title=crud.make_title(payload.message), model=model
        )
    elif convo.model != model:
        convo.model = model
        db.commit()

    conversation_id = convo.id
    title = convo.title

    # Persist the user's message, then assemble the LLM context.
    crud.add_message(db, conversation_id, "user", payload.message, model=None)
    crud.link_attachments(db, payload.attachment_ids, conversation_id)
    messages, has_images = _build_messages(db, conversation_id, payload.system_prompt)
    model = _resolve_model(payload.model, has_images)
    temperature = (
        payload.temperature
        if payload.temperature is not None
        else settings.default_temperature
    )

    def event_stream() -> Iterator[str]:
        yield _sse(
            {
                "type": "meta",
                "conversation_id": conversation_id,
                "title": title,
                "model": model,
                "is_new": is_new,
            }
        )
        full = []
        try:
            for delta in llm.stream_chat(messages, model, temperature):
                full.append(delta)
                yield _sse({"type": "delta", "content": delta})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming failed")
            err = _friendly_error(exc)
            yield _sse({"type": "error", "error": err})
            if full:
                _persist_assistant(conversation_id, "".join(full), model)
            return

        text = "".join(full).strip()
        message_id = None
        if text:
            saved = _persist_assistant(conversation_id, text, model)
            message_id = saved.id if saved else None
        yield _sse({"type": "done", "message_id": message_id})

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable proxy buffering for SSE
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )


@router.post("/chat", response_model=ChatResponse)
@router.post("/chat/", response_model=ChatResponse, include_in_schema=False)
def chat_legacy(payload: ChatRequest, db: Session = Depends(get_db)):
    """Non-streaming endpoint (backward compatible with the original v1 API)."""
    model = payload.model or settings.default_model

    convo = None
    if payload.conversation_id:
        convo = crud.get_conversation(db, payload.conversation_id)
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    if convo is None:
        convo = crud.create_conversation(
            db, title=crud.make_title(payload.message), model=model
        )

    crud.add_message(db, convo.id, "user", payload.message)
    crud.link_attachments(db, payload.attachment_ids, convo.id)
    messages, has_images = _build_messages(db, convo.id, payload.system_prompt)
    model = _resolve_model(payload.model, has_images)
    temperature = (
        payload.temperature
        if payload.temperature is not None
        else settings.default_temperature
    )

    try:
        text = "".join(llm.stream_chat(messages, model, temperature)).strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat failed")
        raise HTTPException(status_code=502, detail=_friendly_error(exc))

    crud.add_message(db, convo.id, "assistant", text, model=model)
    return ChatResponse(response=text, conversation_id=convo.id, model=model)


def _persist_assistant(conversation_id: str, text: str, model: str):
    """Save the assistant message using an independent session (the request
    session may already be closed by the time the generator finishes)."""
    db = SessionLocal()
    try:
        return crud.add_message(db, conversation_id, "assistant", text, model=model)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist assistant message")
        return None
    finally:
        db.close()


def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "api key" in low or "authentication" in low or "401" in low:
        return "Authentication failed. Check that GROQ_API_KEY is valid."
    if "rate limit" in low or "429" in low:
        return "Rate limit reached. Please wait a moment and try again."
    if "model" in low and ("decommission" in low or "not found" in low or "404" in low):
        return "That model is unavailable. Try selecting a different one."
    if "timeout" in low or "timed out" in low:
        return "The request timed out. Please try again."
    return f"Something went wrong: {msg}"