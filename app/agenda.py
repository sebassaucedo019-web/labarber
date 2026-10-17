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
    barber = f" · {html.escape(appointment.barber)}" if appointment.barber else ""
    return f"""
    <article class="appointment {state_class}" data-status="{html.escape(status)}">
      <div class="time-rail"><strong>{html.escape(_format_time(appointment.starts_at))}</strong></div>
      <div class="appointment-body">
        <div class="appointment-head">
          <h3>{html.escape(appointment.customer_name)}</h3>
          <span class="badge">{html.escape(label)}</span>
        </div>
        <p>{html.escape(appointment.service)}{barber}</p>
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
        f"<strong>{day.day}</strong><small>{len(grouped.get(day, [])) or '—'}</small></button>"
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
    summary = f"{len(rows)} cita" + ("s" if len(rows) != 1 else "") + " próximas"
    page = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#144534"><title>__TITLE__ | BARBER CG</title>
<style>
:root{color-scheme:light;font-family:Manrope,system-ui,-apple-system,Segoe UI,sans-serif;background:#edf2ee;color:#17231e}
*{box-sizing:border-box}body{margin:0;min-height:100dvh;background:linear-gradient(180deg,#dfece4 0,#edf2ee 230px,#edf2ee 100%)}main{max-width:640px;margin:0 auto;padding:0 16px 40px}
.topbar{position:sticky;top:0;z-index:2;margin:0 -16px;padding:calc(14px + env(safe-area-inset-top)) 16px 14px;background:rgba(255,255,255,.9);backdrop-filter:blur(16px);border-bottom:1px solid #d7e3da;display:flex;align-items:center;justify-content:space-between;gap:12px}.topbar>div{min-width:0}
.eyebrow{margin:0;color:#46705b;font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase}.topbar h1{margin:3px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:700 19px/24px 'Space Grotesk',sans-serif;color:#17231e}.refresh{min-height:42px;padding:0 13px;border:1px solid #bad0c1;border-radius:10px;background:#fff;color:#144534;font-weight:800;box-shadow:0 2px 5px #173f2b12}.refresh:active{transform:scale(.97)}
.intro{padding:28px 0 16px}.intro-row{display:flex;align-items:end;justify-content:space-between;gap:12px}.intro h2{margin:0;font:700 27px/32px 'Space Grotesk',sans-serif;letter-spacing:.01em}.intro p{margin:6px 0 0;color:#5f7167;font-size:14px}.count{color:#8a6500;font-size:12px;font-weight:900;white-space:nowrap;background:#fff8d9;border:1px solid #f0df9a;border-radius:999px;padding:7px 10px}
.dates{display:flex;gap:9px;overflow-x:auto;padding:2px 0 16px;scrollbar-width:none}.dates::-webkit-scrollbar{display:none}.date-card{flex:0 0 61px;min-height:82px;padding:10px 4px;border:1px solid #d6e2d9;border-radius:12px;background:rgba(255,255,255,.86);color:#34473c;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;box-shadow:0 3px 10px #2249360b}.date-card span{font-size:10px;font-weight:900;text-transform:uppercase;color:#718278}.date-card strong{font:700 22px/25px 'Space Grotesk',sans-serif}.date-card small{font-size:10px;color:#718278}.date-card.selected{background:#144534;border-color:#144534;color:#fff;box-shadow:0 7px 16px #14453435;transform:translateY(-2px)}.date-card.selected span,.date-card.selected small{color:#c9eed8}
.section-heading{display:flex;align-items:center;justify-content:space-between;margin:8px 0 10px}.section-heading h2{margin:0;font:700 18px/24px 'Space Grotesk',sans-serif}.section-heading span{font-size:12px;color:#5f7167;font-weight:800}.day-section{display:none}.day-section.active{display:block}
.appointment{position:relative;display:flex;gap:14px;margin:11px 0;padding:15px 14px 15px 16px;border:1px solid #d9e5dc;border-left:4px solid #74a78a;border-radius:13px;background:rgba(255,255,255,.94);box-shadow:0 4px 12px #22493610}.appointment.next{border:2px solid #144534;padding-left:15px;box-shadow:0 9px 22px #14453420}.appointment.completed{border-left-color:#82918a;opacity:.68}.appointment.cancelled{border-left-color:#d45b5b;background:#fffafa}.time-rail{flex:0 0 72px;padding-top:2px}.time-rail strong{font:700 15px/20px 'Space Grotesk',sans-serif;color:#144534}.appointment.completed .time-rail strong{color:#64756d}.appointment-body{min-width:0;flex:1}.appointment-head{display:flex;align-items:start;justify-content:space-between;gap:8px}.appointment h3{margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:16px;line-height:22px;color:#17231e}.appointment p{margin:4px 0 0;color:#52645a;font-size:13px;line-height:19px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.badge{flex:0 0 auto;border-radius:999px;padding:5px 8px;background:#e3f2e9;color:#144534;font-size:10px;font-weight:900}.next .badge{background:#144534;color:#fff}.cancelled .badge{background:#fef0f0;color:#bd3f3f}.completed .badge{background:#edf1ef;color:#64756d}.empty{padding:28px 16px;border:1px dashed #afc5b5;border-radius:13px;background:rgba(255,255,255,.65);color:#64756d;text-align:center;font-size:14px}.footer{text-align:center;color:#718278;font-size:12px;padding:28px 0}.footer strong{color:#144534}
@media (min-width:640px){main{padding-left:24px;padding-right:24px}.topbar{margin-left:-24px;margin-right:-24px;padding-left:24px;padding-right:24px}}
</style></head><body><main>
<header class="topbar"><div><p class="eyebrow">BARBER CG</p><h1>__TITLE__</h1></div><button class="refresh" id="refresh" type="button" aria-label="Actualizar agenda">↻ Actualizar</button></header>
<section class="intro"><div class="intro-row"><div><h2>Tu agenda</h2><p>Próximos 7 días · Chihuahua</p></div><span class="count">__SUMMARY__</span></div></section>
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
