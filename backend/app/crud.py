"""Reusable persistence helpers built on top of the SQLAlchemy session."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import Attachment, Conversation, Message


def list_conversations(db: Session) -> List[Conversation]:
    stmt = select(Conversation).order_by(Conversation.updated_at.desc())
    return list(db.scalars(stmt))


def get_conversation(db: Session, conversation_id: str) -> Optional[Conversation]:
    return db.get(Conversation, conversation_id)


def create_conversation(
    db: Session, title: Optional[str] = None, model: Optional[str] = None
) -> Conversation:
    convo = Conversation(
        title=title or "New chat",
        model=model or settings.default_model,
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


def rename_conversation(
    db: Session, conversation_id: str, title: str
) -> Optional[Conversation]:
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        return None
    convo.title = title.strip()[:200]
    db.commit()
    db.refresh(convo)
    return convo


def delete_conversation(db: Session, conversation_id: str) -> bool:
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        return False
    db.delete(convo)
    db.commit()
    return True


def delete_all_conversations(db: Session) -> int:
    convos = list(db.scalars(select(Conversation)))
    count = len(convos)
    for c in convos:
        db.delete(c)
    db.commit()
    return count


def _next_seq(db: Session, conversation_id: str) -> int:
    current = db.scalar(
        select(func.max(Message.seq)).where(
            Message.conversation_id == conversation_id
        )
    )
    return (current or 0) + 1


def add_message(
    db: Session,
    conversation_id: str,
    role: str,
    content: str,
    model: Optional[str] = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        model=model,
        seq=_next_seq(db, conversation_id),
    )
    db.add(msg)
    # Touch the parent so it bubbles to the top of the sidebar.
    convo = db.get(Conversation, conversation_id)
    if convo is not None:
        convo.updated_at = func.now()
    db.commit()
    db.refresh(msg)
    return msg


def history_for_llm(
    db: Session, conversation_id: str, limit: int = settings.max_history_messages
) -> List[dict]:
    """Return the most recent messages (oldest-first) as LLM-ready dicts."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    rows = list(db.scalars(stmt))
    rows.reverse()
    return [{"role": m.role, "content": m.content} for m in rows]


def make_title(text: str) -> str:
    """Derive a short conversation title from the first user message."""
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= 48:
        return cleaned or "New chat"
    return cleaned[:48].rsplit(" ", 1)[0] + "\u2026"


# ---------- Attachments ----------
def create_attachment(
    db: Session,
    filename: str,
    content: str,
    truncated: bool = False,
    conversation_id: Optional[str] = None,
) -> Attachment:
    att = Attachment(
        filename=filename[:255],
        content=content,
        chars=len(content),
        truncated=1 if truncated else 0,
        conversation_id=conversation_id,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def link_attachments(
    db: Session, attachment_ids: List[str], conversation_id: str
) -> None:
    """Attach any not-yet-linked uploads to a conversation."""
    if not attachment_ids:
        return
    rows = list(
        db.scalars(select(Attachment).where(Attachment.id.in_(attachment_ids)))
    )
    changed = False
    for att in rows:
        if att.conversation_id is None:
            att.conversation_id = conversation_id
            changed = True
    if changed:
        db.commit()


def attachments_for_conversation(
    db: Session, conversation_id: str
) -> List[Attachment]:
    stmt = (
        select(Attachment)
        .where(Attachment.conversation_id == conversation_id)
        .order_by(Attachment.created_at)
    )
    return list(db.scalars(stmt))


def build_document_context(db: Session, conversation_id: str) -> Optional[str]:
    """Combine all attachment text for a conversation into one context block,
    capped at settings.max_context_chars."""
    atts = attachments_for_conversation(db, conversation_id)
    if not atts:
        return None
    parts: List[str] = []
    used = 0
    for att in atts:
        header = f"\n----- BEGIN FILE: {att.filename} -----\n"
        footer = f"\n----- END FILE: {att.filename} -----\n"
        budget = settings.max_context_chars - used - len(header) - len(footer)
        if budget <= 0:
            break
        body = att.content[:budget]
        parts.append(header + body + footer)
        used += len(header) + len(body) + len(footer)
    if not parts:
        return None
    return (
        "The user has attached the following document(s). Use them to answer "
        "the user's questions. If the answer is not in the documents, say so.\n"
        + "".join(parts)
    )
