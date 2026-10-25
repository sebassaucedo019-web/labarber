import asyncio
import time
from datetime import datetime

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent import agent as agent_module
from app.agent.agent import get_agent
from app.agent.routing import classify_message, get_router
from app.queue import tasks
from app.store.models import Appointment, Base


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_real_agent_tool_roundtrip_and_two_turns(db, monkeypatch):
    async def business(*args):
        return "business"

    monkeypatch.setattr(tasks, "classify_message", business)
    requests = []

    async def response(messages, info):
        requests.append(messages)
        if any(isinstance(p, ToolReturnPart) for p in messages[-1].parts):
            return ModelResponse(parts=[TextPart("No tienes citas próximas.")])
        return ModelResponse(parts=[ToolCallPart("consultar_mi_cita", {}, "lookup")])

    get_agent.cache_clear()
    with get_agent().override(model=FunctionModel(response)):
        for _ in range(2):
            assert (
                tasks._run_agent(db, "526143649949", "Consulta mi cita")
                == "No tienes citas próximas."
            )
    assert len(requests) == 4
    get_agent.cache_clear()


def test_router_structured_output_uses_context_without_tools(monkeypatch):
    received = []

    async def response(messages, info):
        received.append(messages)
        assert not info.function_tools
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"kind": "business"}, "route")]
        )

    get_router.cache_clear()
    with get_router().override(model=FunctionModel(response)):
        assert tasks._run_async(classify_message("pm", "Asistente: ¿9 am o pm?")) == "business"
    assert "9 am o pm" in str(received)
    get_router.cache_clear()


def test_current_date_changes_without_restarting_agent(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 10, 21, 23, 59)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(agent_module, "datetime", Clock)
    assert "2026-10-21 23:59" in agent_module._build_system_prompt()
    Clock.current = datetime(2026, 10, 22, 0, 1)
    assert "2026-10-22 00:01" in agent_module._build_system_prompt()


def test_real_agent_booking_confirms_only_on_second_turn(db, monkeypatch):
    async def business(*args):
        return "business"

    monkeypatch.setattr(tasks, "classify_message", business)

    async def response(messages, info):
        if any(isinstance(p, ToolReturnPart) for p in messages[-1].parts):
            # The server must not send a false success from the model.
            return ModelResponse(parts=[TextPart("Ya estaba guardada")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "agendar",
                    {
                        "fecha_hora": "2090-01-02 12:00",
                        "servicio": "corte normal",
                        "nombre": "Ana",
                        "barbero": "Obed",
                    },
                    "book",
                )
            ]
        )

    get_agent.cache_clear()
    with get_agent().override(model=FunctionModel(response)):
        proposal = tasks._run_agent(db, "526143649949", "Quiero una cita")
        assert "¿Confirmas?" in proposal
        assert db.scalar(select(Appointment)) is None
        result = tasks._run_agent(db, "526143649949", "Si confirmo")
        assert "Cita confirmada" in result
        assert len(db.scalars(select(Appointment)).all()) == 1
    get_agent.cache_clear()


def test_timeout_waits_for_inflight_tool_before_closing_session():
    events = []

    def write_booking() -> str:
        time.sleep(0.05)
        events.append("committed")
        return "confirmed"

    tool = agent_module._transactional_tool(write_booking)

    async def run():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(tool.function(), timeout=0.005)
        events.append("session-closed")

    tasks._run_async(run())
    assert events == ["committed", "session-closed"]
