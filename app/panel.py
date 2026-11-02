"""Private mobile operations on the same appointments the WhatsApp bot uses."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.identity import normalize_phone
from app.panel_auth import Principal, authenticated, authorized_write
from app.scheduling import (
    LABELS,
    audit,
    calendar_lock,
    create_block,
    invalidate_notices,
    local_now,
    transition,
)
from app.staff import names, working_slot
from app.store.models import Appointment, MessagingPreference, NotificationOutbox, ScheduleBlock
from app.store.postgres import get_session

router = APIRouter()
ASSETS = Path(__file__).resolve().parent / "static" / "agenda"


@router.get("/panel", response_class=HTMLResponse)
def panel_page():
    return (Path(__file__).resolve().parent / "templates" / "panel.html").read_text(
        encoding="utf-8"
    )


@router.get("/panel-sw.js")
def service_worker():
    return Response(
        (ASSETS / "panel-sw.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


def serialize(row):
    return {
        "id": row.id,
        "customer": row.customer_name,
        "service": row.service,
        "barber": row.barber,
        "starts_at": row.starts_at.isoformat(),
        "duration_minutes": 30,
        "status": row.status,
        "label": LABELS.get(row.status, row.status),
        "arrived_at": row.arrived_at.isoformat() if row.arrived_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "reminder_consent": row.reminder_consent,
    }


@router.get("/api/agenda/calendar")
def calendar(
    user: Annotated[Principal, Depends(authenticated)],
    start: date | None = None,
    barber: str | None = Query(None, max_length=80),
):
    now = local_now()
    start = start or now.date()
    if not now.date() - timedelta(days=31) <= start <= now.date() + timedelta(days=366):
        raise HTTPException(400, "Elige una fecha entre el mes pasado y el próximo año")
    allowed = names() if user.scope == "all" else [user.scope]
    if barber and barber not in allowed:
        raise HTTPException(403, "Agenda no autorizada")
    visible = [barber] if barber else allowed
    begin = datetime.combine(start, datetime.min.time())
    end = begin + timedelta(days=7)
    with get_session() as session:
        rows = session.scalars(
            select(Appointment)
            .where(
                Appointment.barber.in_(visible),
                Appointment.starts_at >= begin,
                Appointment.starts_at < end,
            )
            .order_by(Appointment.starts_at, Appointment.id)
        ).all()
        blocks = session.scalars(
            select(ScheduleBlock).where(
                ScheduleBlock.barber.in_(visible),
                ScheduleBlock.active.is_(True),
                ScheduleBlock.starts_at < end,
                ScheduleBlock.ends_at > begin,
            )
        ).all()
        occupied = {(a.barber, a.starts_at) for a in rows if a.status != "cancelled"}
        slots = []
        for day in range(7):
            for member in visible:
                for half in range(48):
                    at = begin + timedelta(days=day, minutes=half * 30)
                    if at <= now or not working_slot(member, at) or (member, at) in occupied:
                        continue
                    if any(
                        b.barber == member
                        and b.starts_at < at + timedelta(minutes=30)
                        and b.ends_at > at
                        for b in blocks
                    ):
                        continue
                    slots.append({"barber": member, "starts_at": at.isoformat()})
        return {
            "now": now.isoformat(),
            "start": start.isoformat(),
            "business": get_settings().business_name,
            "scope": user.scope,
            "barbers": allowed,
            "appointments": [serialize(a) for a in rows],
            "available": slots,
            "automatic_notices_enabled": get_settings().automatic_notices_enabled,
            "blocks": [
                {
                    "id": b.id,
                    "barber": b.barber,
                    "starts_at": b.starts_at.isoformat(),
                    "ends_at": b.ends_at.isoformat(),
                    "reason": b.reason,
                }
                for b in blocks
            ],
        }


class StateChange(BaseModel):
    state: Literal["confirmed", "arrived", "in_service", "completed", "no_show"]
    expected_status: str = Field(max_length=16)


@router.post("/api/agenda/appointments/{appointment_id}/state")
def change_state(
    appointment_id: int, body: StateChange, user: Annotated[Principal, Depends(authorized_write)]
):
    with get_session() as session:
        try:
            calendar_lock(session)
            row = session.get(Appointment, appointment_id)
            if row is None or (user.scope != "all" and row.barber != user.scope):
                raise PermissionError("Cita no disponible")
            if row.status != body.expected_status and row.status != body.state:
                raise ValueError("La cita cambió. Actualiza la agenda")
            row = transition(session, appointment_id, user.scope, user.username, body.state)
            session.commit()
            return serialize(row)
        except PermissionError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


class Consent(BaseModel):
    enabled: bool
    source: str = Field(min_length=8, max_length=300)


@router.post("/api/agenda/appointments/{appointment_id}/consent")
def consent(
    appointment_id: int, body: Consent, user: Annotated[Principal, Depends(authorized_write)]
):
    with get_session() as session:
        calendar_lock(session)
        row = session.get(Appointment, appointment_id)
        if row is None or (user.scope != "all" and row.barber != user.scope):
            raise HTTPException(404, "Cita no disponible")
        pref = session.get(MessagingPreference, normalize_phone(row.wa_id))
        if body.enabled and pref and pref.opted_out:
            raise HTTPException(
                409, "El cliente pidió la baja. Debe solicitar ALTA RECORDATORIOS desde su WhatsApp"
            )
        row.reminder_consent, row.consent_source = body.enabled, body.source
        audit(
            session,
            row.id,
            user.username,
            "consent" if body.enabled else "revoke_consent",
            body.source,
        )
        if not body.enabled:
            invalidate_notices(session, row.id)
        session.commit()
        return {"ok": True}


class BlockInput(BaseModel):
    barber: str = Field(max_length=80)
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=1, max_length=200)


@router.post("/api/agenda/blocks")
def add_block(body: BlockInput, user: Annotated[Principal, Depends(authorized_write)]):
    if body.barber not in names() or body.starts_at.tzinfo or body.ends_at.tzinfo:
        raise HTTPException(400, "Usa un barbero configurado y la hora local de Chihuahua")
    with get_session() as session:
        try:
            row = create_block(
                session,
                user.scope,
                user.username,
                body.barber,
                body.starts_at,
                body.ends_at,
                body.reason,
            )
            session.commit()
            return {"id": row.id}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.delete("/api/agenda/blocks/{block_id}")
def remove_block(block_id: int, user: Annotated[Principal, Depends(authorized_write)]):
    if user.scope != "all":
        raise HTTPException(403, "Solo el administrador puede desbloquear")
    with get_session() as session:
        calendar_lock(session)
        row = session.get(ScheduleBlock, block_id)
        if row is None:
            raise HTTPException(404, "Bloqueo no disponible")
        if row.active:
            row.active = False
            audit(session, None, user.username, "unblock", str(block_id))
        session.commit()
        return {"ok": True}


@router.get("/api/agenda/notifications")
def notifications(user: Annotated[Principal, Depends(authenticated)]):
    if user.scope != "all":
        raise HTTPException(403, "Solo el administrador puede consultar los envíos")
    with get_session() as session:
        rows = session.execute(
            select(NotificationOutbox, Appointment.customer_name, Appointment.barber)
            .join(Appointment, Appointment.id == NotificationOutbox.appointment_id)
            .order_by(NotificationOutbox.id.desc())
            .limit(100)
        ).all()
        return [
            {
                "id": n.id,
                "customer": customer,
                "barber": barber,
                "kind": n.kind,
                "status": n.status,
                "attempts": n.attempts,
                "error": n.last_error,
                "accepted_at": n.accepted_at.isoformat() if n.accepted_at else None,
                "delivered_at": n.delivered_at.isoformat() if n.delivered_at else None,
            }
            for n, customer, barber in rows
        ]
