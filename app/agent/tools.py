import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic_ai import RunContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agenda import agenda_link_message, staff_scope
from app.agent.confirmation import confirm_action
from app.agent.deps import BotDeps
from app.config import get_settings
from app.escalation import is_support_request, notify_human
from app.identity import normalize_phone, phone_aliases
from app.store.models import Appointment

SERVICES = {
    "corte normal": 120,
    "corte clásico": 150,
    "corte clasico": 150,
    "barba y corte": 200,
    "servicio completo": 300,
}
BARBERS = {"obed": "Obed", "jesus": "Jesús", "yadier": "Yadier"}
MENU_SENTINEL = "__BARBER_CG_MENU_SENT__"
OPEN_HOUR = 9
CLOSE_HOUR = 20
BUSINESS_TZ = ZoneInfo("America/Chihuahua")
logger = logging.getLogger(__name__)


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
    if normalized == "corte clasico":
        normalized = "corte clásico"
    return normalized if normalized in SERVICES else None


def _barber_key(barber: str) -> str | None:
    normalized = " ".join(barber.lower().strip().split()).replace("ú", "u")
    return BARBERS.get(normalized)


def _valid_slot(starts_at: datetime) -> bool:
    return OPEN_HOUR <= starts_at.hour < CLOSE_HOUR and starts_at.minute in (0, 30)


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
    rows = ctx.deps.db.scalars(
        select(Appointment)
        .where(
            Appointment.starts_at >= start,
            Appointment.starts_at < start.replace(hour=CLOSE_HOUR),
            Appointment.barber == barber,
            Appointment.status == "confirmed",
        )
        .order_by(Appointment.starts_at)
    ).all()
    occupied = {row.starts_at.strftime("%H:%M") for row in rows}
    now = _now()
    available = [
        candidate.strftime("%H:%M")
        for i in range(22)
        for candidate in (start + timedelta(minutes=30 * i),)
        if candidate.strftime("%H:%M") not in occupied and (day != now.date() or candidate > now)
    ]
    return f"Horarios disponibles para {fecha}: {', '.join(available) or 'no hay espacios'}."


def _staff_recipient(barber: str) -> str | None:
    settings = get_settings()
    configured = {
        "Obed": settings.barber_obed_wa_id,
        "Jesús": settings.barber_jesus_wa_id,
        "Yadier": settings.barber_yadier_wa_id,
    }.get(barber)
    return configured if normalize_phone(configured) else None


def _staff_recipients(appointment: Appointment) -> list[str]:
    settings = get_settings()
    recipients = [
        recipient
        for recipient in (
            settings.owner_wa_id,
            _staff_recipient(appointment.barber or ""),
        )
        if recipient
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for recipient in recipients:
        key = normalize_phone(recipient)
        if key and key not in seen:
            seen.add(key)
            unique.append(recipient)
    return unique


def _notify_staff(appointment: Appointment, message: str) -> None:
    for recipient in _staff_recipients(appointment):
        _send_notification(recipient, message)


def _send_notification(recipient: str, message: str) -> None:
    from app.notifications import notify

    notify(recipient, message)


def _notify_staff_of_appointment(appointment: Appointment) -> None:
    _notify_staff(
        appointment,
        "Confirmación de cita en BARBER CG 💈\n"
        f"{_format_appointment(appointment)}\n"
        f"Cliente: {appointment.customer_name}\n"
        "La cita quedó confirmada.",
    )


def _staff_access(wa_id: str) -> tuple[bool, str | None]:
    """Dueño ve toda la agenda; cada barbero solo la suya. Clientes no acceden."""
    scope = staff_scope(wa_id)
    return scope == "all", scope if scope != "all" else None


def _format_appointment(appointment: Appointment) -> str:
    price = SERVICES.get(appointment.service, 0)
    return (
        f"{appointment.starts_at:%d/%m/%Y} {appointment.starts_at:%H:%M} — "
        f"{appointment.customer_name}, {appointment.service} (${price} MXN), "
        f"con {appointment.barber or 'barbero por asignar'}"
    )


def ver_siguiente_cita(ctx: RunContext[BotDeps]) -> str:
    """Muestra la siguiente cita al dueño o al barbero que consulta."""
    is_admin, barber_filter = _staff_access(ctx.deps.wa_id)
    if not is_admin and barber_filter is None:
        return "Esta consulta está disponible únicamente para el dueño o los barberos de BARBER CG."
    conditions = [Appointment.starts_at >= _now(), Appointment.status == "confirmed"]
    if barber_filter:
        conditions.append(Appointment.barber == barber_filter)
    appointment = ctx.deps.db.scalar(
        select(Appointment).where(*conditions).order_by(Appointment.starts_at)
    )
    if appointment is None:
        return "No hay citas próximas confirmadas."
    return f"La siguiente cita es el {_format_appointment(appointment)}."


def ver_agenda(ctx: RunContext[BotDeps]) -> str:
    """Lista citas próximas: el dueño ve todas; cada barbero ve las suyas."""
    is_admin, barber_filter = _staff_access(ctx.deps.wa_id)
    if not is_admin and barber_filter is None:
        return "Esta consulta está disponible únicamente para el dueño o los barberos de BARBER CG."
    conditions = [Appointment.starts_at >= _now(), Appointment.status == "confirmed"]
    if barber_filter:
        conditions.append(Appointment.barber == barber_filter)
    rows = ctx.deps.db.scalars(
        select(Appointment).where(*conditions).order_by(Appointment.starts_at).limit(15)
    ).all()
    if not rows:
        return "No hay citas próximas confirmadas."
    header = "Próximas citas:" if is_admin else f"Tus próximas citas ({barber_filter}):"
    return header + "\n" + "\n".join(_format_appointment(row) for row in rows)


def obtener_enlace_agenda(ctx: RunContext[BotDeps]) -> str:
    """Genera un enlace móvil temporal para el dueño o el barbero autenticado."""
    return agenda_link_message(ctx.deps.wa_id)


def mostrar_menu_principal(ctx: RunContext[BotDeps]) -> str:
    """Muestra botones cuando la IA identifica un saludo o bienvenida."""
    ctx.deps.menu_sent = True
    return MENU_SENTINEL


def consultar_mi_cita(ctx: RunContext[BotDeps]) -> str:
    """Muestra al cliente sus próximas citas sin exponer la agenda de otros."""
    rows = ctx.deps.db.scalars(
        select(Appointment)
        .where(
            Appointment.wa_id.in_(phone_aliases(ctx.deps.wa_id)),
            Appointment.starts_at >= _now(),
            Appointment.status == "confirmed",
        )
        .order_by(Appointment.starts_at)
        .limit(5)
    ).all()
    if not rows:
        return "No encontré citas próximas a tu nombre o número."
    return "Tus próximas citas son:\n" + "\n".join(f"• {_format_appointment(row)}" for row in rows)


def agendar(
    ctx: RunContext[BotDeps], fecha_hora: str, servicio: str, nombre: str, barbero: str
) -> str:
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
    conflict = ctx.deps.db.scalar(
        select(Appointment).where(
            Appointment.starts_at == starts_at,
            Appointment.barber == barber,
            Appointment.status == "confirmed",
        )
    )
    if conflict:
        if (
            conflict.wa_id in phone_aliases(ctx.deps.wa_id)
            and conflict.customer_name.casefold() == nombre.strip().casefold()
            and _service_key(conflict.service) == service
        ):
            return f"La cita ya estaba confirmada: {_format_appointment(conflict)}."
        return "Ese horario ya está ocupado. Consulta disponibilidad para elegir otro."
    if not confirm_action(
        ctx.deps,
        "book",
        {
            "starts_at": starts_at.isoformat(),
            "service": service,
            "name": nombre.strip()[:120],
            "barber": barber,
        },
        f"Reservar para {nombre.strip()[:120]}: {service} (${SERVICES[service]} MXN), "
        f"{starts_at:%d/%m/%Y %H:%M} con {barber}.",
    ):
        return ctx.deps.pending_action_reply
    ctx.deps.db.add(
        Appointment(
            wa_id=ctx.deps.wa_id,
            customer_name=nombre.strip()[:120],
            service=service,
            barber=barber,
            starts_at=starts_at,
        )
    )
    try:
        ctx.deps.db.commit()
    except IntegrityError:
        ctx.deps.db.rollback()
        return "Ese horario acaba de ocuparse. Consulta disponibilidad para elegir otro."
    confirmation = (
        f"Cita confirmada para {nombre.strip()}, {service} "
        f"(${SERVICES[service]} MXN), el {starts_at:%d/%m/%Y} "
        f"a las {starts_at:%H:%M}, con {barber}."
    )
    ctx.deps.completed_actions.append(confirmation)
    appointment = ctx.deps.db.scalar(
        select(Appointment).where(
            Appointment.wa_id == ctx.deps.wa_id,
            Appointment.starts_at == starts_at,
            Appointment.barber == barber,
            Appointment.status == "confirmed",
        )
    )
    if appointment is not None:
        _notify_staff_of_appointment(appointment)
    return confirmation


def cancelar_cita(
    ctx: RunContext[BotDeps],
    fecha_hora: str,
    cliente: str | None = None,
    cita_id: int | None = None,
) -> str:
    """Cancela una cita propia o una cita del equipo con permiso de staff."""
    starts_at = _parse_datetime(fecha_hora)
    if starts_at is None:
        return "Necesito fecha y hora como AAAA-MM-DD HH:MM."
    is_admin, barber_filter = _staff_access(ctx.deps.wa_id)
    conditions = [
        Appointment.starts_at == starts_at,
        Appointment.status == "confirmed",
    ]
    if is_admin:
        pass
    elif barber_filter:
        conditions.append(Appointment.barber == barber_filter)
    else:
        conditions.append(Appointment.wa_id.in_(phone_aliases(ctx.deps.wa_id)))
    if cita_id is not None:
        conditions.append(Appointment.id == cita_id)
    appointments = ctx.deps.db.scalars(
        select(Appointment).where(*conditions).with_for_update()
    ).all()
    if cliente:
        wanted = " ".join(cliente.split()).casefold()
        appointments = [
            row for row in appointments if " ".join(row.customer_name.split()).casefold() == wanted
        ]
    appointment = appointments[0] if len(appointments) == 1 else None
    if len(appointments) > 1:
        return _ambiguous_appointments(appointments)
    if appointment is None:
        if barber_filter:
            return "No encontré una cita de ese barbero en ese horario."
        return "No encontré una cita confirmada en ese horario."
    if not is_admin and barber_filter is None and starts_at - _now() < timedelta(hours=3):
        return "No se puede cancelar con menos de 3 horas de anticipación."
    if not confirm_action(
        ctx.deps,
        "cancel",
        {
            "appointment_id": appointment.id,
            "starts_at": starts_at.isoformat(),
            "barber": appointment.barber,
        },
        "Cancelar: " + _format_appointment(appointment) + ".",
    ):
        return ctx.deps.pending_action_reply
    appointment.status = "cancelled"
    ctx.deps.db.commit()
    confirmation = f"Cita cancelada correctamente: {_format_appointment(appointment)}."
    ctx.deps.completed_actions.append(confirmation)
    _notify_staff(
        appointment,
        "Cita cancelada en BARBER CG 💈\n"
        f"{_format_appointment(appointment)}\n"
        f"Cliente: {appointment.customer_name}",
    )
    if (is_admin or barber_filter) and normalize_phone(appointment.wa_id) != normalize_phone(
        ctx.deps.wa_id
    ):
        _send_notification(
            appointment.wa_id,
            "BARBER CG canceló tu cita: "
            + _format_appointment(appointment)
            + ". Escríbenos para elegir otro horario.",
        )
    return confirmation


def _ambiguous_appointments(appointments: list[Appointment]) -> str:
    options = "\n".join(f"Referencia {row.id}: {_format_appointment(row)}" for row in appointments)
    return "Hay varias citas en ese horario. Confirma cuál quieres modificar:\n" + options


def reagendar_cita(
    ctx: RunContext[BotDeps],
    fecha_actual: str,
    fecha_nueva: str,
    nuevo_barbero: str | None = None,
    cliente: str | None = None,
    cita_id: int | None = None,
) -> str:
    """Mueve una cita propia, incluso a otro barbero, si el horario está libre."""
    old = _parse_datetime(fecha_actual)
    new = _parse_datetime(fecha_nueva)
    if old is None or new is None:
        return "Necesito ambas fechas como AAAA-MM-DD HH:MM."
    conditions = [
        Appointment.wa_id.in_(phone_aliases(ctx.deps.wa_id)),
        Appointment.starts_at == old,
        Appointment.status == "confirmed",
    ]
    if cita_id is not None:
        conditions.append(Appointment.id == cita_id)
    appointments = ctx.deps.db.scalars(
        select(Appointment).where(*conditions).with_for_update()
    ).all()
    if cliente:
        wanted = " ".join(cliente.split()).casefold()
        appointments = [
            row for row in appointments if " ".join(row.customer_name.split()).casefold() == wanted
        ]
    if len(appointments) > 1:
        return _ambiguous_appointments(appointments)
    appointment = appointments[0] if appointments else None
    if appointment is None:
        return "No encontré una cita confirmada en el horario actual."
    if old <= _now():
        return "Esa cita ya pasó. Podemos agendar una nueva."
    target_barber = appointment.barber
    if nuevo_barbero:
        target_barber = _barber_key(nuevo_barbero)
        if target_barber is None:
            return "Elige uno de estos barberos: Obed, Jesús o Yadier."
    if not _valid_slot(new) or new <= _now():
        return "El nuevo horario debe estar entre 09:00 y 19:30 y ser futuro."
    if target_barber is None:
        return "Elige uno de estos barberos: Obed, Jesús o Yadier."
    if new == old and target_barber == appointment.barber:
        return f"La cita ya tiene ese horario y barbero: {_format_appointment(appointment)}."
    if ctx.deps.db.scalar(
        select(Appointment).where(
            Appointment.id != appointment.id,
            Appointment.starts_at == new,
            Appointment.barber == target_barber,
            Appointment.status == "confirmed",
        )
    ):
        return "El nuevo horario ya está ocupado."
    if not confirm_action(
        ctx.deps,
        "reschedule",
        {
            "appointment_id": appointment.id,
            "old": old.isoformat(),
            "new": new.isoformat(),
            "old_barber": appointment.barber,
            "new_barber": target_barber,
        },
        f"Cambiar la cita de {appointment.customer_name} del {old:%d/%m/%Y %H:%M} "
        f"al {new:%d/%m/%Y %H:%M} con {target_barber}.",
    ):
        return ctx.deps.pending_action_reply
    old_starts_at = appointment.starts_at
    old_barber = appointment.barber
    appointment.starts_at = new
    appointment.barber = target_barber
    try:
        ctx.deps.db.commit()
    except IntegrityError:
        ctx.deps.db.rollback()
        return "El nuevo horario acaba de ocuparse. Consulta disponibilidad para elegir otro."
    confirmation = f"Cita reagendada para el {new:%d/%m/%Y} a las {new:%H:%M} con {target_barber}."
    ctx.deps.completed_actions.append(confirmation)
    if old_starts_at == new and old_barber != target_barber:
        staff_message = (
            "Cambio de barbero en BARBER CG 💈\n"
            f"Cliente: {appointment.customer_name}\n"
            f"Horario: {new:%d/%m/%Y %H:%M}\n"
            f"Barbero anterior: {old_barber}\n"
            f"Barbero nuevo: {target_barber}"
        )
    elif old_starts_at != new and old_barber == target_barber:
        staff_message = (
            "Cita reagendada en BARBER CG 💈\n"
            f"Cliente: {appointment.customer_name}\n"
            f"Antes: {old_starts_at:%d/%m/%Y %H:%M}\n"
            f"Ahora: {new:%d/%m/%Y %H:%M}\n"
            f"Barbero: {target_barber}"
        )
    else:
        staff_message = (
            "Cambio de barbero y horario en BARBER CG 💈\n"
            f"Cliente: {appointment.customer_name}\n"
            f"Antes: {old_starts_at:%d/%m/%Y %H:%M} con {old_barber}\n"
            f"Ahora: {new:%d/%m/%Y %H:%M} con {target_barber}"
        )
    _notify_staff(
        appointment,
        staff_message,
    )
    if old_barber and old_barber != target_barber:
        old_recipient = _staff_recipient(old_barber)
        new_recipients = {
            normalize_phone(recipient) for recipient in _staff_recipients(appointment)
        }
        if old_recipient and normalize_phone(old_recipient) not in new_recipients:
            _send_notification(
                old_recipient,
                "Cambio de cita en BARBER CG 💈\n"
                f"La cita de {appointment.customer_name} pasó de {old_barber} a {target_barber}.\n"
                f"Nueva fecha: {new:%d/%m/%Y %H:%M}.",
            )
    return confirmation


def escalar_humano(ctx: RunContext[BotDeps], motivo: str) -> str:
    """Deriva la conversación a una persona del equipo."""
    if not is_support_request(ctx.deps.user_message):
        return "No se envió aviso. Solo se escala una solicitud explícita de atención o un problema de la barbería."
    notified = notify_human(ctx.deps.wa_id, ctx.deps.user_message[:1000])
    if not notified:
        return "No pude entregar el aviso al equipo. Intenta de nuevo en un momento."
    return "Ya envié tu solicitud al equipo de la barbería."
