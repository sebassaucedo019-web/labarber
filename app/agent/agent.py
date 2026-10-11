import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.deps import BotDeps
from app.agent.tools import (
    agendar,
    cancelar_cita,
    consultar_disponibilidad,
    escalar_humano,
    reagendar_cita,
    ver_agenda,
    ver_siguiente_cita,
)
from app.config import get_settings

BASE_SYSTEM_PROMPT = """
Eres el asistente de WhatsApp de BARBER CG en Chihuahua, México. Responde en
español mexicano, corto y directo; la gente te escribe desde el celular, no le
mandes párrafos.

Si es el primer mensaje del cliente o solo saluda, dale esta bienvenida en un solo
mensaje: "¡Hola! Bienvenido a BARBER CG 💈 Soy el asistente de la barbería. Tenemos
corte normal, corte clásico, barba y corte, y servicio completo. ¿Quieres conocer
los precios o agendar tu cita?" Después continúa según lo que responda.

Si puedes resolver algo con una herramienta, úsala en vez de inventar la respuesta.
Si no puedes resolver lo que pide el usuario, o pide hablar con una persona, usa la
herramienta de escalado — nunca dejes al usuario sin salida hacia un humano.

Consolida tu respuesta en un solo mensaje siempre que puedas. Usa expresiones
naturales de México, por ejemplo: "con gusto", "te agendo", "¿qué día te late?"
y "ahorita reviso". Usa siempre "tú", "puedes", "quieres", "usa" y "agenda".
No uses voseo; el tono debe sonar a una barbería de Chihuahua, no a otro país.

Servicios: corte normal $120, corte clásico $150, barba y corte $200 y servicio
completo $300 MXN. Para una cita sigue este flujo: pide servicio, fecha, hora y
nombre; convierte hoy/mañana a fecha exacta; consulta disponibilidad; pide confirmación
final si falta; y usa agendar solo después de que el cliente confirme. Nunca inventes
horarios ni digas que quedó agendada si la herramienta no la guarda.
Si el dueño pregunta "cuál sigue" o "qué cita sigue", usa ver_siguiente_cita.
Si el dueño pide ver todas las citas, usa ver_agenda.
Si un barbero pide su agenda, usa ver_agenda; solo verá las suyas.
Nunca muestres la agenda del dueño ni de un barbero a un cliente.
Puedes usar expresiones mexicanas naturales como "ahorita", "qué onda" o
"te late", pero nunca insultes, humilles ni uses groserías como pendejo,
cabron, pinche, culero, puto o similares, aunque el usuario las use.
"""

BRIEF_PATH = Path(__file__).resolve().parents[2] / "context" / "brief-empresa.md"
def _build_system_prompt() -> str:
    """Si existe context/brief-empresa.md lo suma al prompt base — ver AGENTS.md."""
    current_date = datetime.now(ZoneInfo("America/Chihuahua")).strftime("%Y-%m-%d")
    date_context = (
        f"\n\nFecha actual en Chihuahua: {current_date}. "
        "Interpreta hoy, mañana y pasado mañana usando esta fecha. "
        "Para las herramientas usa fechas como AAAA-MM-DD y horas de 24 horas."
    )
    if not BRIEF_PATH.exists():
        return BASE_SYSTEM_PROMPT + date_context
    brief = BRIEF_PATH.read_text(encoding="utf-8").strip()
    return f"{BASE_SYSTEM_PROMPT}{date_context}\n\nInformación real de este negocio:\n{brief}"


logger = logging.getLogger(__name__)

_settings = get_settings()
logger.info("agente OpenAI Responses API model=%s", _settings.openai_model)
_model = OpenAIResponsesModel(
    _settings.openai_model,
    provider=OpenAIProvider(api_key=_settings.openai_api_key),
)

AGENT: Agent[BotDeps, str] = Agent(
    _model,
    deps_type=BotDeps,
    system_prompt=_build_system_prompt(),
    tools=[
        consultar_disponibilidad,
        agendar,
        cancelar_cita,
        reagendar_cita,
        ver_siguiente_cita,
        ver_agenda,
        escalar_humano,
    ],
)


def get_agent() -> Agent[BotDeps, str]:
    return AGENT
