from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.config import get_settings
from app.store.models import Appointment
from app.store.postgres import get_session

router = APIRouter()
BUSINESS_TZ = ZoneInfo("America/Chihuahua")
TOKEN_TTL_SECONDS = 24 * 60 * 60
DEFAULT_PUBLIC_BASE_URL = "https://labarber-production-b9de.up.railway.app"


def _last10(value: str | None) -> str | None:
    digits = "".join(char for char in value if char.isdigit()) if value else ""
    return digits[-10:] if len(digits) >= 10 else None


def staff_scope(wa_id: str) -> str | None:
    """Return all or the barber name that this staff number may see."""
    settings = get_settings()
    caller = _last10(wa_id)
    if not caller:
        return None
    if _last10(settings.owner_wa_id) == caller:
        return "all"
    for name, configured in (
        ("Obed", settings.barber_obed_wa_id),
        ("Jesús", settings.barber_jesus_wa_id),
        ("Yadier", settings.barber_yadier_wa_id),
    ):
        if _last10(configured) == caller:
            return name
    return None


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_agenda_link(wa_id: str) -> str | None:
    scope = staff_scope(wa_id)
    if scope is None:
        return None
    payload = _encode(json.dumps(
        {"scope": scope, "exp": int(time.time()) + TOKEN_TTL_SECONDS},
        separators=(",", ":"),
    ).encode())
    secret = get_settings().meta_app_secret.encode()
    signature = _encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
    base_url = (get_settings().public_base_url or DEFAULT_PUBLIC_BASE_URL).rstrip("/")
    return f"{base_url}/agenda?token={quote(payload + '.' + signature)}"


def is_agenda_link_request(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return re.search(r"\bagenda\b", normalized) is not None and any(
        re.search(pattern, normalized)
        for pattern in (
            r"\bmi\b", r"\blink\b", r"\benlace\b", r"\bcelular\b", r"\bweb\b",
            r"\bver\b", r"\bquiero\b", r"\bdame\b", r"\bpasa(?:me)?\b",
            r"\bmanda(?:me)?\b",
        )
    )


def agenda_link_message(wa_id: str) -> str:
    link = create_agenda_link(wa_id)
    if link is None:
        return "Esta función está disponible únicamente para el dueño o los barberos de BARBER CG."
    return f"Aquí tienes tu agenda en el celular (el enlace dura 24 horas):\n{link}"


def _verify_token(token: str) -> str | None:
    try:
        payload, signature = token.split(".", 1)
        secret = get_settings().meta_app_secret.encode()
        expected = _encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_decode(payload))
        if int(data["exp"]) < int(time.time()):
            return None
        scope = data["scope"]
        return scope if scope == "all" or scope in {"Obed", "Jesús", "Yadier"} else None
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


def _format_row(appointment: Appointment) -> str:
    time_value = appointment.starts_at.strftime("%H:%M")
    return (
        "<article class='appointment'>"
        f"<strong>{html.escape(time_value)}</strong>"
        f"<span>{html.escape(appointment.customer_name)}</span>"
        f"<small>{html.escape(appointment.service)} · {html.escape(appointment.barber or 'Sin asignar')}</small>"
        "</article>"
    )


def _day_heading(day: date, today: date) -> str:
    names = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    if day == today:
        label = "Hoy"
    elif day == today + timedelta(days=1):
        label = "Mañana"
    else:
        label = names[day.weekday()].capitalize()
    return f"{label} · {day:%d/%m/%Y}"


@router.get("/agenda", response_class=HTMLResponse)
def agenda_page(token: str = Query(default="")) -> str:
    scope = _verify_token(token)
    if scope is None:
        return HTMLResponse(
            "<h1>Enlace no válido</h1><p>Solicita un enlace nuevo desde WhatsApp.</p>",
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
    now = datetime.now(BUSINESS_TZ).replace(tzinfo=None)
    conditions = [
        Appointment.starts_at >= now,
        Appointment.starts_at < now + timedelta(days=14),
        Appointment.status == "confirmed",
    ]
    if scope != "all":
        conditions.append(Appointment.barber == scope)
    session = get_session()
    try:
        rows = session.scalars(
            select(Appointment).where(*conditions).order_by(Appointment.starts_at).limit(50)
        ).all()
    finally:
        session.close()
    title = "Agenda general" if scope == "all" else f"Agenda de {scope}"
    grouped: dict[date, list[Appointment]] = defaultdict(list)
    for row in rows:
        grouped[row.starts_at.date()].append(row)
    sections = "".join(
        f"<section><h2>{html.escape(_day_heading(day, now.date()))}</h2>"
        f"{''.join(_format_row(row) for row in day_rows)}</section>"
        for day, day_rows in grouped.items()
    )
    content = sections or "<p class='empty'>No hay citas próximas en los siguientes 14 días.</p>"
    summary = f"{len(rows)} cita" + ("s" if len(rows) != 1 else "") + " próximas"
    return HTMLResponse(f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} | BARBER CG</title>
<style>
:root {{ color-scheme: light; font-family: system-ui,-apple-system,Segoe UI,sans-serif; background:#f5f6f3; color:#17231e; }}
body {{ margin:0; }} main {{ max-width:680px; margin:0 auto; padding:24px 16px 40px; }}
header {{ background:#173b31; color:white; padding:20px; border-radius:16px; margin-bottom:16px; }}
h1 {{ margin:0 0 6px; font-size:24px; }} header p {{ margin:0; opacity:.8; }}
section {{ margin:20px 0 26px; }} h2 {{ font-size:16px; margin:0 0 8px; color:#315d4d; }}
.appointment {{ background:white; border:1px solid #dce4de; border-left:5px solid #3d8b70; border-radius:12px; padding:15px; margin:10px 0; display:grid; gap:5px; box-shadow:0 2px 8px #173b3110; }}
.appointment strong {{ font-size:23px; color:#17664d; }} .appointment span {{ font-weight:600; }}
.appointment small {{ color:#63716a; font-size:14px; }} .empty {{ background:white; padding:20px; border-radius:12px; color:#63716a; }}
</style></head><body><main><header><h1>💈 {html.escape(title)}</h1><p>BARBER CG · {summary}</p></header>{content}</main></body></html>""", headers={"Cache-Control": "no-store"})
