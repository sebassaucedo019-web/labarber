from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from string import Template
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.config import get_settings
from app.identity import normalize_phone
from app.store.models import Appointment
from app.store.postgres import get_session

router = APIRouter()
BUSINESS_TZ = ZoneInfo("America/Chihuahua")
TOKEN_TTL_SECONDS = 24 * 60 * 60
DEFAULT_PUBLIC_BASE_URL = "https://labarber-production-b9de.up.railway.app"


def staff_scope(wa_id: str) -> str | None:
    """Return all or the barber name that this staff number may see."""
    settings = get_settings()
    caller = normalize_phone(wa_id)
    if not caller:
        return None
    if normalize_phone(settings.owner_wa_id) == caller:
        return "all"
    for name, configured in (
        ("Obed", settings.barber_obed_wa_id),
        ("Jesús", settings.barber_jesus_wa_id),
        ("Yadier", settings.barber_yadier_wa_id),
    ):
        if normalize_phone(configured) == caller:
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
    payload = _encode(
        json.dumps(
            {
                "scope": scope,
                "sub": normalize_phone(wa_id),
                "exp": int(time.time()) + TOKEN_TTL_SECONDS,
            },
            separators=(",", ":"),
        ).encode()
    )
    secret = get_settings().meta_app_secret.encode()
    signature = _encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
    base_url = (get_settings().public_base_url or DEFAULT_PUBLIC_BASE_URL).rstrip("/")
    return f"{base_url}/agenda?token={quote(payload + '.' + signature)}"


def is_agenda_link_request(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    # Staff often sends only "link" from WhatsApp. Treat only short, explicit
    # link requests as agenda requests; never confuse "agendar" with "agenda".
    if re.fullmatch(
        r"(?:link|enlace|url|liga|pasame el link|dame el link|mandame el enlace)[!.? ]*", normalized
    ):
        return True
    return re.search(r"\bagenda\b", normalized) is not None and any(
        re.search(pattern, normalized)
        for pattern in (
            r"\bmi\b",
            r"\blink\b",
            r"\benlace\b",
            r"\bcelular\b",
            r"\bweb\b",
            r"\bver\b",
            r"\bquiero\b",
            r"\bdame\b",
            r"\bpasa(?:me)?\b",
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
        if not token.isascii() or len(token) > 1024:
            return None
        payload, signature = token.split(".", 1)
        secret = get_settings().meta_app_secret.encode()
        expected = _encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_decode(payload))
        if not isinstance(data, dict) or type(data.get("exp")) is not int:
            return None
        if data["exp"] <= int(time.time()):
            return None
        scope = data["scope"]
        subject = data.get("sub")
        if not isinstance(subject, str) or scope != staff_scope(subject):
            return None
        return scope if scope in {"all", "Obed", "Jesús", "Yadier"} else None
    except (binascii.Error, KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


def _format_time(value: datetime) -> str:
    hour = value.hour % 12 or 12
    suffix = "a. m." if value.hour < 12 else "p. m."
    return f"{hour}:{value:%M} {suffix}"


ASSET_DIR = Path(__file__).resolve().parent / "static" / "agenda"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _icon(name: str) -> str:
    return (
        '<svg class="icon" aria-hidden="true" focusable="false" fill="none" '
        'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        'stroke-linejoin="round" viewBox="0 0 24 24">'
        f'<use href="/agenda-assets/icons.svg#{name}"></use></svg>'
    )


def _format_row(appointment: Appointment, *, is_next: bool = False) -> str:
    labels = {"confirmed": "Confirmada", "completed": "Completada", "cancelled": "Cancelada"}
    status = appointment.status if appointment.status in labels else "confirmed"
    barber_class = {"Obed": "obed", "Jesús": "jesus", "Yadier": "yadier"}.get(
        appointment.barber,
        "unassigned",
    )
    time = appointment.starts_at
    period = "a. m." if time.hour < 12 else "p. m."
    next_label = f'<span class="next-label">{_icon("clock")}Siguiente</span>' if is_next else ""
    check = _icon("check") if status != "cancelled" else ""
    barber_label = html.escape(appointment.barber or "Sin asignar")
    return f"""
    <article class="appointment {status}{" next" if is_next else ""}" data-status="{status}">
      <time class="time-rail" datetime="{time.isoformat()}" aria-label="{_format_time(time)}">
        <span class="time-number">{time.hour % 12 or 12}:{time:%M}</span>
        <span class="time-period">{period}</span>
      </time>
      <div class="appointment-body">
        <h3>{html.escape(appointment.customer_name.title())}</h3>
        <p class="service">{html.escape(appointment.service.title())}</p>
        <div class="appointment-meta">
          <span class="barber barber-{barber_class}">{barber_label}</span>
          <span class="badge">{check}{labels[status]}</span>
          {next_label}
        </div>
      </div>
    </article>"""


def _day_heading(day: date, today: date) -> str:
    names = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    label = (
        "Hoy"
        if day == today
        else "Mañana"
        if day == today + timedelta(days=1)
        else names[day.weekday()].capitalize()
    )
    return f"{label}, {day.day} de {MONTHS[day.month - 1]}"


def _date_range(start: date, end: date) -> str:
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day} al {end.day} de {MONTHS[end.month - 1]} de {end.year}"
    start_label = f"{start.day} de {MONTHS[start.month - 1]}"
    if start.year != end.year:
        start_label += f" de {start.year}"
    return f"{start_label} al {end.day} de {MONTHS[end.month - 1]} de {end.year}"


def _html_response(page: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        page,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )


def render_agenda(rows: list[Appointment], scope: str, now: datetime) -> str:
    """Presentation only: authorization and database selection stay in the route."""
    days = [now.date() + timedelta(days=offset) for offset in range(7)]
    grouped: dict[date, list[Appointment]] = defaultdict(list)
    for row in rows:
        grouped[row.starts_at.date()].append(row)
    next_id = rows[0].id if rows else None
    spanish_days = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
    buttons, sections = [], []
    for index, day in enumerate(days):
        day_rows = grouped.get(day, [])
        total = f"{len(day_rows)} cita{'s' if len(day_rows) != 1 else ''}"
        heading = _day_heading(day, now.date())
        key = day.isoformat()
        buttons.append(
            f'<button class="date-tab{" has-appointments" if day_rows else ""}" type="button" '
            f'role="tab" id="tab-{key}" aria-controls="day-{key}" '
            f'aria-selected="{str(index == 0).lower()}" tabindex="{0 if index == 0 else -1}" '
            f'data-day="{key}" aria-label="{html.escape(heading)}; {total}">'
            f'<span class="weekday">{"Hoy" if index == 0 else spanish_days[day.weekday()]}</span>'
            f'<span class="day-number">{day.day}</span>'
            '<span class="day-dot" aria-hidden="true"></span></button>'
        )
        rows_markup = "".join(_format_row(row, is_next=row.id == next_id) for row in day_rows)
        if rows_markup:
            rows_markup = f'<div class="appointments">{rows_markup}</div>'
        else:
            rows_markup = (
                f'<div class="empty"><span class="empty-icon">{_icon("calendar")}</span>'
                "<p>Sin citas este día</p></div>"
            )
        sections.append(
            f'<section class="day-section" role="tabpanel" id="day-{key}" '
            f'aria-labelledby="tab-{key}" data-day-section="{key}" tabindex="0"'
            f"{' hidden' if index else ''}>"
            f'<div class="section-heading"><h2>{html.escape(heading)}</h2>'
            f'<span class="day-total">{total}</span></div>{rows_markup}</section>'
        )
    title = "Agenda general" if scope == "all" else f"Agenda de {scope}"
    template = Template((TEMPLATE_DIR / "agenda.html").read_text(encoding="utf-8"))
    return template.substitute(
        title=html.escape(title),
        scope_label="Todo el equipo" if scope == "all" else f"Tu agenda, {html.escape(scope)}",
        date_range=html.escape(_date_range(days[0], days[-1])),
        summary=f"{len(rows)} cita próxima" if len(rows) == 1 else f"{len(rows)} citas próximas",
        dates="".join(buttons),
        sections="".join(sections),
        updated_at=_format_time(now),
        scissors_icon=_icon("scissors"),
        lock_icon=_icon("lock"),
        refresh_icon=_icon("refresh"),
        clock_icon=_icon("clock"),
    )


@router.get("/agenda", response_class=HTMLResponse)
def agenda_page(token: str = Query(default="")) -> HTMLResponse:
    scope = _verify_token(token)
    if scope is None:
        template = Template((TEMPLATE_DIR / "agenda_expired.html").read_text(encoding="utf-8"))
        return _html_response(
            template.substitute(
                scissors_icon=_icon("scissors"),
                lock_icon=_icon("lock"),
            ),
            status_code=403,
        )
    now = datetime.now(BUSINESS_TZ).replace(tzinfo=None)
    conditions = [
        Appointment.starts_at >= now,
        Appointment.starts_at
        < datetime.combine(now.date() + timedelta(days=7), datetime.min.time()),
        Appointment.status == "confirmed",
    ]
    if scope != "all":
        conditions.append(Appointment.barber == scope)
    session = get_session()
    try:
        rows = session.scalars(
            select(Appointment).where(*conditions).order_by(Appointment.starts_at, Appointment.id)
        ).all()
    finally:
        session.close()
    return _html_response(render_agenda(rows, scope, now))
