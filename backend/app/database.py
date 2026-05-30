"""Database layer: SQLAlchemy models, engine and session management.

Conversations and messages are persisted to SQLite so that chat history
survives restarts — a key requirement for a production-grade assistant.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from .config import settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    model: Mapped[str] = mapped_column(String(120), default=settings.default_model)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Attachment(Base):
    """An uploaded document whose extracted text is injected into the LLM
    context for its conversation. `conversation_id` is nullable so a file can
    be uploaded before the first message is sent (linked on first send)."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)            # extracted plain text
    chars: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[int] = mapped_column(Integer, default=0)  # 0/1 flag
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# SQLite needs check_same_thread disabled because FastAPI uses a thread pool.
_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables. For SQLite, ensure the parent directory exists."""
    if settings.database_url.startswith("sqlite"):
        import os

        path = settings.database_url.replace("sqlite:///", "", 1)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
