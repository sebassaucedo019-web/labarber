from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    """Estado del hilo por wa_id: el historial que le pasamos al agente en cada turno."""

    __tablename__ = "conversations"

    wa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    history_json: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MessageLog(Base):
    """Auditoría de mensajes. wa_id va hasheado acá — no es el hilo operativo."""

    __tablename__ = "message_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    wa_id_hash: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
