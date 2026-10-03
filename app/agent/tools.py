from pydantic_ai import RunContext

from app.agent.deps import BotDeps
from app.escalation import notify_human


def buscar_pedido(ctx: RunContext[BotDeps], numero_pedido: str) -> str:
    """Busca el estado de un pedido por su número. Reemplazá esto por tu sistema real
    (base de datos de pedidos, API de tu e-commerce, etc.)."""
    return f"Pedido {numero_pedido}: en preparación, llega en 2-3 días hábiles (dato de ejemplo)."


def agendar(ctx: RunContext[BotDeps], fecha: str, motivo: str) -> str:
    """Agenda un turno o cita en la fecha indicada. Reemplazá esto por tu calendario real
    (Google Calendar, Cal.com, tu sistema de turnos, etc.)."""
    return f"Quedó agendado para {fecha} ({motivo}). (dato de ejemplo, no se guardó en ningún lado)"


def escalar_humano(ctx: RunContext[BotDeps], motivo: str) -> str:
    """Deriva la conversación a un humano cuando el bot no puede resolver el pedido del
    usuario, o el usuario lo pide explícitamente. No es opcional: todo bot necesita salida
    a una persona. Ya notifica de verdad vía ESCALATION_WEBHOOK_URL (ver
    docs/08-escalado-a-humano.md) — configurá esa variable, no hace falta tocar este
    código para tener escalado funcionando."""
    notify_human(ctx.deps.wa_id, motivo)
    return f"Listo, aviso a una persona del equipo (motivo: {motivo}). En breve te escriben."
