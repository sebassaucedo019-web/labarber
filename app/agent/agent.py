from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.deps import BotDeps
from app.agent.tools import agendar, buscar_pedido, escalar_humano
from app.config import get_settings

BASE_SYSTEM_PROMPT = """
Sos el asistente de WhatsApp de este negocio. Respondé en español, corto y directo:
la gente te escribe desde el celular, no le mandes párrafos.

Si podés resolver algo con una herramienta, usala en vez de inventar la respuesta.
Si no podés resolver lo que pide el usuario, o pide hablar con una persona, usá la
herramienta de escalado — nunca dejes al usuario sin salida hacia un humano.

Consolidá tu respuesta en un solo mensaje siempre que puedas: cada mensaje saliente
tiene costo, y cinco mensajitos cortos salen más caro que uno bien armado.
"""

BRIEF_PATH = Path(__file__).resolve().parents[2] / "context" / "brief-empresa.md"


def _build_system_prompt() -> str:
    """Si existe context/brief-empresa.md lo suma al prompt base — ver AGENTS.md."""
    if not BRIEF_PATH.exists():
        return BASE_SYSTEM_PROMPT
    brief = BRIEF_PATH.read_text(encoding="utf-8").strip()
    return f"{BASE_SYSTEM_PROMPT}\n\nInformación real de este negocio:\n{brief}"


_settings = get_settings()
_model = OpenAIChatModel(
    _settings.openai_model,
    provider=OpenAIProvider(api_key=_settings.openai_api_key),
)

AGENT: Agent[BotDeps, str] = Agent(
    _model,
    deps_type=BotDeps,
    system_prompt=_build_system_prompt(),
    tools=[buscar_pedido, agendar, escalar_humano],
)


def get_agent() -> Agent[BotDeps, str]:
    return AGENT
