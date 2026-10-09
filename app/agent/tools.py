from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic_ai import RunContext
from sqlalchemy import select

from app.agent.deps import BotDeps
from app.config import get_settings
from app.escalation import notify_human
from app.store.models import Appointment

SERVICES = {
    "corte normal": 120,
    "corte clásico": 150,
    "corte clasico": 150,
    "barba y corte": 200,
    "servicio completo": 300,
}
BARBERS = {"obed": "Obed", "jesus": "Jesús", "yadier": "Yadier"}
OPEN_HOUR = 9
CLOSE_HOUR = 20
BUSINESS_TZ = ZoneInfo("America/Chihuahua")


def _now() -> datetime:
    """Hora local de Chihuahua sin tz para compararla con SQLite."""
    return datetime.now(BUSINESS_TZ).replace(tzinfo=None)


def _parse_datetime(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            pass
    return None


def _service_key(service: str) -> str | None:
    normalized = " ".join(service.lower().strip().split())
    return normalized if normalized in SERVICES else None


def _barber_key(barber: str) -> str | None:
    normalized = " ".join(barber.lower().strip().split()).replace("ú", "u")
    return BARBERS.get(normalized)


def _valid_slot(starts_at: datetime) -> bool:
    return (
        OPEN_HOUR <= starts_at.hour < CLOSE_HOUR
        and starts_at.minute in (0, 30)
    )


def buscar_pedido(ctx: RunContext[BotDeps], numero_pedido: str) -> str:
    """Compatibilidad con la plantilla original; BARBER CG no usa pedidos."""
    return f"Pedido {numero_pedido}: función no disponible en BARBER CG."


def consultar_disponibilidad(ctx: RunContext[BotDeps], fecha: str, barbero: str) -> str:
    """Consulta las horas ocupadas para una fecha YYYY-MM-DD."""
    try:
        day = datetime.strptime(fecha.strip(), "%Y-%m-%d").date()
    except ValueError:
        return "Necesito la fecha en formato AAAA-MM-DD."
    if day < _now().date():
        return "Esa fecha ya pasó. Dime otra fecha y reviso los horarios."
    barber = _barber_key(barbero)
    if barber is None:
        return "Elige uno de estos barberos: Obed, Jesús o Yadier."
    start = datetime.combine(day, datetime.min.time()).replace(hour=OPEN_HOUR)
    rows = ctx.deps.db.scalars(select(Appointment).where(
        Appointment.starts_at >= start,
        Appointment.starts_at < start.replace(hour=CLOSE_HOUR),
        Appointment.barber == barber,
        Appointment.status == "confirmed",
    ).order_by(Appointment.starts_at)).all()
    occupied = {row.starts_at.strftime("%H:%M") for row in rows}
    available = [
        (start + timedelta(minutes=30 * i)).strftime("%H:%M")
        for i in range(22)
        if (start + timedelta(minutes=30 * i)).strftime("%H:%M") not in occupied
    ]
    return f"Horarios disponibles para {fecha}: {', '.join(available) or 'no hay espacios'}."


def ver_siguiente_cita(ctx: RunContext[BotDeps]) -> str:
    """Muestra la siguiente cita únicamente al número del dueño configurado."""
    settings = get_settings()
    caller = ctx.deps.wa_id[-10:]
    access = {
        "Obed": settings.barber_obed_wa_id,
        "Jesús": settings.barber_jesus_wa_id,
        "Yadier": settings.barber_yadier_wa_id,
    }
    is_admin = bool(settings.owner_wa_id and caller == settings.owner_wa_id.replace("+", "")[-10:])
    if is_admin:
        barber_filter = None
    else:
        barber_filter = next(
            (name for name, wa_id in access.items()
             if wa_id and caller == wa_id.replace("+", "")[-10:]),
            None,
        )
    if not is_admin and barber_filter is None:
        return "Esta consulta está disponible únicamente para el dueño de BARBER CG."
    conditions = [Appointment.starts_at >= _now(), Appointment.status == "confirmed"]
    if barber_filter:
        conditions.append(Appointment.barber == barber_filter)
    appointment = ctx.deps.db.scalar(select(Appointment).where(*conditions).order_by(Appointment.starts_at))
    if appointment is None:
        return "No hay citas próximas confirmadas."
    price = SERVICES.get(appointment.service, 0)
    return (
        f"La siguiente cita es el {appointment.starts_at:%d/%m/%Y} a las "
        f"{appointment.starts_at:%H:%M}: {appointment.customer_name}, "
        f"{appointment.service} (${price} MXN), con {appointment.barber or 'barbero por asignar'}."
    )


def agendar(ctx: RunContext[BotDeps], fecha_hora: str, servicio: str, nombre: str, barbero: str) -> str:
    """Guarda una cita tras validar servicio, horario y disponibilidad."""
    starts_at = _parse_datetime(fecha_hora)
    service = _service_key(servicio)
    barber = _barber_key(barbero)
    if starts_at is None:
        return "Necesito fecha y hora como AAAA-MM-DD HH:MM."
    if service is None:
        return (
            "Ese servicio no existe. Ofrecemos corte normal, corte clásico, "
            "barba y corte o servicio completo."
        )
    if barber is None:
        return "Elige uno de estos barberos: Obed, Jesús o Yadier."
    if not _valid_slot(starts_at):
        return "Atendemos de 09:00 a 20:00; elige una hora en punto o a los 30 minutos."
    if not nombre.strip():
        return "También necesito tu nombre para reservar la cita."
    if starts_at <= _now():
        return "Esa fecha y hora ya pasó."
    conflict = ctx.deps.db.scalar(select(Appointment).where(
        Appointment.starts_at == starts_at,
        Appointment.barber == barber,
        Appointment.status == "confirmed",
    ))
    if conflict:
        return "Ese horario ya está ocupado. Consulta disponibilidad para elegir otro."
    ctx.deps.db.add(Appointment(
        wa_id=ctx.deps.wa_id,
        customer_name=nombre.strip(),
        service=service,
        barber=barber,
        starts_at=starts_at,
    ))
    ctx.deps.db.commit()
    return (
        f"Cita confirmada para {nombre.strip()}, {service} "
        f"(${SERVICES[service]} MXN), el {starts_at:%d/%m/%Y} "
        f"a las {starts_at:%H:%M}, con {barber}."
    )


def cancelar_cita(ctx: RunContext[BotDeps], fecha_hora: str) -> str:
    """Cancela una cita propia si faltan al menos 3 horas."""
    starts_at = _parse_datetime(fecha_hora)
    if starts_at is None:
        return "Necesito fecha y hora como AAAA-MM-DD HH:MM."
    appointment = ctx.deps.db.scalar(select(Appointment).where(
        Appointment.wa_id == ctx.deps.wa_id,
        Appointment.starts_at == starts_at,
        Appointment.status == "confirmed",
    ))
    if appointment is None:
        return "No encontré una cita confirmada en ese horario."
    if starts_at - _now() < timedelta(hours=3):
        return "No se puede cancelar con menos de 3 horas de anticipación."
    appointment.status = "cancelled"
    ctx.deps.db.commit()
    return "Tu cita fue cancelada correctamente."


def reagendar_cita(ctx: RunContext[BotDeps], fecha_actual: str, fecha_nueva: str) -> str:
    """Mueve una cita propia a un horario libre."""
    old = _parse_datetime(fecha_actual)
    new = _parse_datetime(fecha_nueva)
    if old is None or new is None:
        return "Necesito ambas fechas como AAAA-MM-DD HH:MM."
    appointment = ctx.deps.db.scalar(select(Appointment).where(
        Appointment.wa_id == ctx.deps.wa_id,
        Appointment.starts_at == old,
        Appointment.status == "confirmed",
    ))
    if appointment is None:
        return "No encontré una cita confirmada en el horario actual."
    if not _valid_slot(new) or new <= _now():
        return "El nuevo horario debe estar entre 09:00 y 19:30 y ser futuro."
    if ctx.deps.db.scalar(select(Appointment).where(
        Appointment.starts_at == new,
        Appointment.barber == appointment.barber,
        Appointment.status == "confirmed")):
        return "El nuevo horario ya está ocupado."
    appointment.starts_at = new
    ctx.deps.db.commit()
    return f"Cita reagendada para el {new:%d/%m/%Y} a las {new:%H:%M}."


def escalar_humano(ctx: RunContext[BotDeps], motivo: str) -> str:
    """Deriva la conversación a una persona del equipo."""
    notify_human(ctx.deps.wa_id, motivo)
    return f"Listo, aviso a una persona del equipo (motivo: {motivo}). En breve te escriben."
