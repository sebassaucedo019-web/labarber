from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
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


class Appointment(Base):
    """Citas confirmadas de la barberia."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    service: Mapped[str] = mapped_column(String(80))
    barber: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="confirmed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        # Prevent two workers from confirming the same barber and time under load.
        Index(
            "uq_confirmed_barber_slot",
            "starts_at",
            "barber",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
            sqlite_where=text("status = 'confirmed'"),
        ),
    )
