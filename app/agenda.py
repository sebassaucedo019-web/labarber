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
    # Staff often sends only "link" from WhatsApp. Treat only short, explicit
    # link requests as agenda requests; never confuse "agendar" with "agenda".
    if re.fullmatch(r"(?:link|enlace|url|liga|pasame el link|dame el link|mandame el enlace)[!.? ]*", normalized):
        return True
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
    except (binascii.Error, KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


def _format_time(value: datetime) -> str:
    hour = value.hour % 12 or 12
    suffix = "a. m." if value.hour < 12 else "p. m."
    return f"{hour}:{value:%M} {suffix}"


def _format_row(appointment: Appointment, *, is_next: bool = False) -> str:
    status = appointment.status or "confirmed"
    labels = {"confirmed": "Confirmada", "completed": "Atendida", "cancelled": "Cancelada"}
    label = labels.get(status, status.capitalize())
    state_class = "next" if is_next else status
    barber_name = html.escape(appointment.barber) if appointment.barber else "Sin asignar"
    barber_class = (appointment.barber or "sin-asignar").lower().replace("é", "e").replace(" ", "-")
    return f"""
    <article class="appointment {state_class}" data-status="{html.escape(status)}">
      <div class="time-rail"><strong>{html.escape(_format_time(appointment.starts_at))}</strong></div>
      <div class="appointment-body">
        <div class="appointment-head">
          <h3>{html.escape(appointment.customer_name)}</h3>
          <span class="badge">{html.escape(label)}</span>
        </div>
        <p class="appointment-meta"><span class="service">{html.escape(appointment.service)}</span>
        <span class="barber barber-{html.escape(barber_class)}">{barber_name}</span></p>
      </div>
    </article>"""


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
    days = [now.date() + timedelta(days=offset) for offset in range(7)]
    conditions = [
        Appointment.starts_at >= now,
        Appointment.starts_at < datetime.combine(days[-1] + timedelta(days=1), datetime.min.time()),
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
    next_id = rows[0].id if rows else None
    spanish_days = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
    date_buttons = "".join(
        f"<button class='date-card{' selected' if day == days[0] else ''}' data-day='{day.isoformat()}' "
        f"aria-label='{html.escape(_day_heading(day, now.date()))}'><span>{spanish_days[day.weekday()]}</span>"
        f"<strong>{day.day}</strong><small>{len(grouped.get(day, [])) or ''}</small></button>"
        for day in days
    )
    sections = []
    for day in days:
        day_rows = grouped.get(day, [])
        rows_markup = "".join(_format_row(row, is_next=row.id == next_id) for row in day_rows)
        if not rows_markup:
            rows_markup = "<div class='empty'>No hay citas programadas para este día.</div>"
        sections.append(
            f"<section class='day-section{' active' if day == days[0] else ''}' data-day-section='{day.isoformat()}'>"
            f"<div class='section-heading'><h2>{html.escape(_day_heading(day, now.date()))}</h2>"
            f"<span>{len(day_rows)} cita{'s' if len(day_rows) != 1 else ''}</span></div>{rows_markup}</section>"
        )
    summary = f"{len(rows)} cita próxima" if len(rows) == 1 else f"{len(rows)} citas próximas"
    page = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#14412F"><title>__TITLE__ | BARBER CG</title>
<style>
:root{color-scheme:light;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:#F6F3EC;color:#19221D}
*{box-sizing:border-box}body{margin:0;min-height:100dvh;background:#F6F3EC}main{max-width:720px;margin:0 auto;padding:28px 18px 48px}
.topbar{display:block;padding:12px 0 0;border-bottom:0}.topbar>div{min-width:0}.eyebrow{display:none}.topbar h1{margin:0;font-family:Georgia,"Times New Roman",serif;font-size:clamp(34px,8vw,48px);font-weight:600;line-height:1.05;letter-spacing:-.02em;color:#19221D}.refresh{float:right;margin-top:-38px;min-height:42px;padding:0 14px;border:1px solid #d5cec0;border-radius:10px;background:transparent;color:#14412F;font-size:13px;font-weight:700;transition:background 150ms ease,transform 150ms ease}.refresh:hover{background:#fff}.refresh:active{transform:scale(.97)}
.intro{padding:9px 0 26px}.intro-row{display:flex;align-items:end;justify-content:space-between;gap:16px}.intro h2{display:none}.intro p{margin:0;color:#756f66;font-size:14px;line-height:20px}.count{color:#14412F;font-size:13px;font-weight:700;white-space:nowrap}
.dates{display:flex;gap:8px;overflow-x:auto;padding:0 0 22px;scrollbar-width:none}.dates::-webkit-scrollbar{display:none}.date-card{position:relative;flex:1 0 56px;min-height:72px;padding:9px 5px;border:1px solid #ded8cc;border-radius:999px;background:transparent;color:#756f66;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;transition:background 150ms ease,color 150ms ease,border-color 150ms ease,transform 150ms ease}.date-card span{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}.date-card strong{font-family:Georgia,"Times New Roman",serif;font-size:22px;font-weight:600;line-height:25px}.date-card small{width:5px;height:5px;border-radius:50%;background:#B08D57;font-size:0;opacity:0}.date-card:not(:has(small:empty)) small{opacity:1}.date-card.selected{background:#14412F;border-color:#14412F;color:#fff;transform:translateY(-2px)}.date-card.selected small{background:#E0C38E}.date-card:hover{border-color:#B08D57}
.section-heading{display:flex;align-items:center;justify-content:space-between;margin:2px 0 12px}.section-heading h2{margin:0;font-family:Georgia,"Times New Roman",serif;font-size:24px;font-weight:600;line-height:30px;color:#19221D}.section-heading span{font-size:12px;color:#756f66;font-weight:700}.day-section{display:none}.day-section.active{display:block;animation:show-day 150ms ease both}@keyframes show-day{from{opacity:.35;transform:translateY(3px)}to{opacity:1;transform:none}}
.appointment{display:flex;gap:18px;margin:11px 0;padding:18px 16px;border:1px solid #ded8cc;border-radius:14px;background:#fff;box-shadow:0 3px 14px rgba(40,32,20,.06);transition:transform 150ms ease,box-shadow 150ms ease}.appointment:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(40,32,20,.09)}.appointment.next{border-color:#B08D57;box-shadow:0 5px 18px rgba(176,141,87,.16)}.appointment.cancelled{border-color:#d8d5cf;background:#faf9f6;opacity:.78}.appointment.completed{border-color:#e1c995}.time-rail{flex:0 0 74px;padding-top:1px}.time-rail strong{font-family:Georgia,"Times New Roman",serif;font-size:22px;font-weight:600;line-height:28px;color:#14412F}.appointment-body{min-width:0;flex:1}.appointment-head{display:flex;align-items:start;justify-content:space-between;gap:10px}.appointment h3{margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-transform:capitalize;font-size:16px;line-height:22px;color:#19221D}.appointment-meta{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin:7px 0 0;color:#756f66;font-size:13px;line-height:20px}.service{text-transform:capitalize}.barber{display:inline-flex;align-items:center;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700;line-height:17px}.barber-obed{background:#e6f0e9;color:#24543b}.barber-jesus{background:#f2e9dc;color:#76572e}.barber-yadier{background:#e6edf1;color:#385767}.barber-sin-asignar{background:#eeece7;color:#756f66}.badge{flex:0 0 auto;border-radius:999px;padding:4px 8px;font-size:10px;font-weight:800;line-height:15px}.appointment[data-status="confirmed"] .badge{background:#e6f0e9;color:#24543b}.appointment[data-status="cancelled"] .badge{background:#eeece7;color:#756f66}.appointment[data-status="completed"] .badge{background:#f2e9dc;color:#76572e}.next .badge{background:#14412F!important;color:#fff!important}.empty{padding:30px 16px;border:1px dashed #c9c1b4;border-radius:14px;background:transparent;color:#756f66;text-align:center;font-size:14px}.footer{text-align:center;color:#8a8379;font-size:12px;padding:30px 0 0}.footer strong{color:#14412F}
@media (min-width:640px){main{padding:52px 30px 64px}.refresh{margin-top:-42px}.dates{gap:10px}.date-card{flex-basis:72px}.appointment{padding:20px}}
</style></head><body><main>
<header class="topbar"><div><h1>Agenda</h1></div><button class="refresh" id="refresh" type="button" aria-label="Actualizar agenda">Actualizar</button></header>
<section class="intro"><div class="intro-row"><p>Próximos 7 días · Chihuahua</p><span class="count">__SUMMARY__</span></div></section>
<nav class="dates" aria-label="Seleccionar día">__DATES__</nav><div id="sections">__SECTIONS__</div>
<footer class="footer">Agenda privada de <strong>BARBER CG</strong><br>Actualizada al abrir esta página</footer>
</main><script>
const buttons=[...document.querySelectorAll('.date-card')], sections=[...document.querySelectorAll('.day-section')];
function selectDay(day){buttons.forEach(b=>b.classList.toggle('selected',b.dataset.day===day));sections.forEach(s=>s.classList.toggle('active',s.dataset.daySection===day));}
buttons.forEach(b=>b.addEventListener('click',()=>selectDay(b.dataset.day)));
document.getElementById('refresh')?.addEventListener('click',()=>{const b=document.getElementById('refresh');b.textContent='✓ Actualizada';setTimeout(()=>location.reload(),500)});
</script></body></html>"""
    page = (page.replace("__TITLE__", html.escape(title))
        .replace("__SUMMARY__", html.escape(summary))
        .replace("__DATES__", date_buttons)
        .replace("__SECTIONS__", "".join(sections)))
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})
