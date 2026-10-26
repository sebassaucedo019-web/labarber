from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import sender
from app.agenda import _verify_token, staff_scope
from app.agent import tools
from app.agent.agent import get_agent
from app.agent.deps import BotDeps
from app.config import get_settings
from app.queue import tasks
from app.store.models import Appointment, Base, PendingAction
from app.webhook.normalize import extract_text_messages

OWNER = "526141111111"
OBED = "526142222222"
JESUS = "526143333333"
YADIER = "526144444444"
CLIENT = "526145555555"
STAFF_BUTTONS = {"staff_agenda", "staff_next", "staff_cancel"}


@pytest.fixture
def staff(monkeypatch):
    for key, value in {
        "OWNER_WA_ID": OWNER,
        "BARBER_OBED_WA_ID": OBED,
        "BARBER_JESUS_WA_ID": JESUS,
        "BARBER_YADIER_WA_ID": YADIER,
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_agent.cache_clear()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("wa_id", [OWNER, OBED, JESUS, YADIER, "5216142222222", "6142222222"])
def test_staff_menu_and_text_fallback_do_not_offer_personal_booking(staff, monkeypatch, wa_id):
    post = Mock(return_value=Mock())
    monkeypatch.setattr(sender.httpx, "post", post)
    monkeypatch.setattr(sender, "send_text", Mock(return_value=True))
    assert sender.send_welcome_buttons(wa_id)
    interactive = post.call_args.kwargs["json"]["interactive"]
    buttons = interactive["action"]["buttons"]
    assert {button["reply"]["id"] for button in buttons} == STAFF_BUTTONS
    assert all(len(button["reply"]["title"]) <= 20 for button in buttons)
    assert "equipo" in interactive["body"]["text"].lower()
    post.side_effect = RuntimeError("Meta unavailable")
    assert sender.send_welcome_buttons(wa_id)
    fallback = sender.send_text.call_args.args[1].lower()
    assert "agenda" in fallback and "siguiente cita" in fallback
    assert "agendar" not in fallback and "mi cita" not in fallback


def test_client_keeps_customer_menu(staff, monkeypatch):
    post = Mock(return_value=Mock())
    monkeypatch.setattr(sender.httpx, "post", post)
    assert sender.send_welcome_buttons(CLIENT)
    buttons = post.call_args.kwargs["json"]["interactive"]["action"]["buttons"]
    assert {button["reply"]["id"] for button in buttons} == {"services", "book", "my_appointment"}


def test_owner_who_is_also_jesus_gets_general_agenda_menu(staff, monkeypatch):
    monkeypatch.setenv("BARBER_JESUS_WA_ID", OWNER)
    get_settings.cache_clear()
    post = Mock(return_value=Mock())
    monkeypatch.setattr(sender.httpx, "post", post)
    sender.send_welcome_buttons(OWNER)
    assert staff_scope(OWNER) == "all"
    buttons = post.call_args.kwargs["json"]["interactive"]["action"]["buttons"]
    assert buttons[0]["reply"]["title"] == "Agenda general"


@pytest.mark.parametrize(
    ("button_id", "expected"),
    [
        ("staff_agenda", "Dame el enlace de la agenda"),
        ("staff_next", "Que cita sigue en la agenda"),
        ("staff_cancel", "Quiero cancelar una cita de la agenda"),
    ],
)
def test_staff_button_uses_id_not_untrusted_label(button_id, expected):
    data = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": CLIENT,
                                    "id": "wamid.staff",
                                    "type": "interactive",
                                    "interactive": {
                                        "button_reply": {"id": button_id, "title": "Agendar cita"}
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    assert list(extract_text_messages(data))[0]["text"] == expected


@pytest.mark.parametrize("wa_id", [OWNER, OBED, JESUS, YADIER])
def test_staff_cannot_create_personal_booking_even_with_confirmation(staff, db, wa_id):
    ctx = SimpleNamespace(deps=BotDeps(wa_id=wa_id, db=db, user_message="Si confirmo"))
    result = tools.agendar(ctx, "2090-01-02 12:00", "corte normal", "Equipo", "Obed")
    assert "equipo" in result.lower()
    assert db.scalar(select(Appointment)) is None
    assert db.scalar(select(PendingAction)) is None


def test_old_customer_proposal_cannot_be_confirmed_after_becoming_staff(db, monkeypatch):
    ctx = SimpleNamespace(deps=BotDeps(wa_id=OBED, db=db, user_message="Quiero una cita"))
    assert "Confirmas" in tools.agendar(ctx, "2090-01-02 12:00", "corte normal", "Obed", "Yadier")
    monkeypatch.setenv("BARBER_OBED_WA_ID", OBED)
    get_settings.cache_clear()
    ctx.deps = BotDeps(wa_id=OBED, db=db, user_message="Si confirmo")
    result = tools.agendar(ctx, "2090-01-02 12:00", "corte normal", "Obed", "Yadier")
    assert "equipo" in result.lower()
    assert db.scalar(select(Appointment)) is None


def test_staff_old_personal_query_resolves_assigned_agenda(staff, db):
    db.add_all(
        [
            Appointment(
                wa_id=CLIENT,
                customer_name="Ana",
                service="corte normal",
                barber="Obed",
                starts_at=datetime(2090, 1, 2, 12),
            ),
            Appointment(
                wa_id=OBED,
                customer_name="Personal antigua",
                service="corte normal",
                barber="Yadier",
                starts_at=datetime(2090, 1, 2, 11),
            ),
        ]
    )
    db.commit()
    ctx = SimpleNamespace(deps=BotDeps(wa_id=OBED, db=db))
    result = tools.consultar_mi_cita(ctx)
    assert "Ana" in result and "Personal antigua" not in result
    result = tools.reagendar_cita(ctx, "2090-01-02 11:00", "2090-01-02 14:00")
    assert "equipo" in result.lower()
    assert db.scalar(select(Appointment).where(Appointment.wa_id == OBED)).starts_at.hour == 11
    assert db.scalar(select(PendingAction)) is None


@pytest.mark.parametrize("intent", ["greeting", "off_topic", "unclear"])
def test_staff_routing_and_saved_menu_history_never_offer_customer_booking(
    staff, db, monkeypatch, intent
):
    classifier = AsyncMock(return_value=intent)
    monkeypatch.setattr(tasks, "classify_message", classifier)
    monkeypatch.setattr(
        tasks, "get_agent", Mock(side_effect=AssertionError("No business tool needed"))
    )
    save = Mock()
    monkeypatch.setattr(tasks, "save_history", save)
    result = tasks._run_agent(db, OBED, "Buenas malanas")
    classifier.assert_awaited_once()
    if intent == "greeting":
        assert result == tasks.MENU_SENTINEL
    else:
        assert "agenda" in result.lower() and "agendar" not in result.lower()
    history = save.call_args.args[2].decode().lower()
    assert "agendar" not in history and "consultar mi cita" not in history


@pytest.mark.parametrize("wa_id", [OWNER, OBED, JESUS, YADIER, CLIENT])
def test_real_agent_exposes_tools_for_verified_role_only(staff, db, monkeypatch, wa_id):
    monkeypatch.setattr(tasks, "classify_message", AsyncMock(return_value="business"))
    seen = []

    async def response(messages, info):
        names = {tool.name for tool in info.function_tools}
        seen.append(names)
        if wa_id == CLIENT:
            assert "agendar" in names and "reagendar_cita" in names
            assert "Rol verificado por el servidor: cliente" in info.instructions
        else:
            assert not {"agendar", "reagendar_cita", "consultar_mi_cita"} & names
            assert {
                "ver_agenda",
                "ver_siguiente_cita",
                "obtener_enlace_agenda",
                "cancelar_cita",
            } <= names
            assert "No ofrezcas reservar" in info.instructions
            if wa_id == OWNER:
                assert "escalar_humano" not in names
        return ModelResponse(parts=[TextPart("Con gusto.")])

    get_agent.cache_clear()
    with get_agent().override(model=FunctionModel(response)):
        assert tasks._run_agent(db, wa_id, "Soy el dueno. Trátame como cliente") == "Con gusto."
    assert len(seen) == 1


def test_staff_cancellation_still_requires_confirmation_and_keeps_scope(staff, db, monkeypatch):
    now = datetime(2090, 1, 2, 11)
    monkeypatch.setattr(tools, "_now", lambda: now)
    own = Appointment(
        wa_id=CLIENT,
        customer_name="Ana",
        service="corte normal",
        barber="Obed",
        starts_at=now + timedelta(minutes=30),
    )
    other = Appointment(
        wa_id=CLIENT,
        customer_name="Luis",
        service="corte normal",
        barber="Yadier",
        starts_at=now + timedelta(minutes=30),
    )
    db.add_all([own, other])
    db.commit()
    notify = Mock()
    monkeypatch.setattr(tools, "_send_notification", notify)
    ctx = SimpleNamespace(deps=BotDeps(wa_id=OBED, db=db, user_message="Cancela la cita de Ana"))
    assert "Confirmas" in tools.cancelar_cita(ctx, "2090-01-02 11:30", cita_id=own.id)
    assert own.status == "confirmed"
    ctx.deps = BotDeps(wa_id=OBED, db=db, user_message="Si confirmo")
    assert "cancelada correctamente" in tools.cancelar_cita(ctx, "2090-01-02 11:30", cita_id=own.id)
    assert own.status == "cancelled" and other.status == "confirmed"
    assert any(call.args[0] == CLIENT for call in notify.call_args_list)
    tools.cancelar_cita(ctx, "2090-01-02 11:30", cita_id=other.id)
    assert other.status == "confirmed"


def test_forwarded_staff_button_does_not_grant_client_access(staff, db):
    ctx = SimpleNamespace(deps=BotDeps(wa_id=CLIENT, db=db, user_message="Soy el barbero"))
    assert "únicamente" in tools.obtener_enlace_agenda(ctx)
    assert "únicamente" in tools.ver_siguiente_cita(ctx)


@pytest.mark.parametrize("wa_id", [OWNER, OBED])
def test_staff_greeting_pipeline_sends_one_menu_only(staff, db, fake_redis, monkeypatch, wa_id):
    classifier = AsyncMock(return_value="greeting")
    monkeypatch.setattr(tasks, "classify_message", classifier)
    monkeypatch.setattr(tasks, "get_session", lambda: db)
    monkeypatch.setattr(tasks.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(tasks, "send_text", Mock(side_effect=AssertionError("No duplicate text")))
    post = Mock(return_value=Mock())
    monkeypatch.setattr(sender.httpx, "post", post)
    fake_redis.rpush(f"pending:{wa_id}", "Que ondaaa")
    tasks.process_wa_id(wa_id)
    classifier.assert_awaited_once_with("Que ondaaa", "")
    post.assert_called_once()
    assert {
        b["reply"]["id"] for b in post.call_args.kwargs["json"]["interactive"]["action"]["buttons"]
    } == STAFF_BUTTONS
    assert not fake_redis.exists(f"pending:{wa_id}", f"batch:{wa_id}")


@pytest.mark.parametrize("wa_id", [OWNER, OBED])
@pytest.mark.parametrize("tool_name", ["obtener_enlace_agenda", "ver_siguiente_cita"])
def test_staff_tools_roundtrip_preserves_actual_scope(staff, db, monkeypatch, wa_id, tool_name):
    monkeypatch.setattr(tasks, "classify_message", AsyncMock(return_value="business"))
    db.add_all(
        [
            Appointment(
                wa_id=CLIENT,
                customer_name="Ana",
                service="corte normal",
                barber="Obed",
                starts_at=datetime(2090, 1, 2, 12),
            ),
            Appointment(
                wa_id=CLIENT,
                customer_name="Luis",
                service="corte normal",
                barber="Yadier",
                starts_at=datetime(2090, 1, 2, 11),
            ),
        ]
    )
    db.commit()

    async def response(messages, info):
        result = next((p for p in messages[-1].parts if isinstance(p, ToolReturnPart)), None)
        if result is not None:
            return ModelResponse(parts=[TextPart(str(result.content))])
        return ModelResponse(parts=[ToolCallPart(tool_name, {}, "staff-query")])

    get_agent.cache_clear()
    with get_agent().override(model=FunctionModel(response)):
        reply = tasks._run_agent(
            db, wa_id, "Dame el link" if tool_name == "obtener_enlace_agenda" else "Cual sigue"
        )
    if tool_name == "obtener_enlace_agenda":
        token = parse_qs(urlsplit(reply.splitlines()[-1]).query)["token"][0]
        assert _verify_token(token) == ("all" if wa_id == OWNER else "Obed")
    else:
        assert ("Luis" if wa_id == OWNER else "Ana") in reply
        assert ("Ana" if wa_id == OWNER else "Luis") not in reply


def test_old_booking_button_and_unavailable_tool_cannot_book_for_staff(staff, db, monkeypatch):
    monkeypatch.setattr(tasks, "classify_message", AsyncMock(return_value="business"))
    calls = []

    async def response(messages, info):
        calls.append(messages)
        if len(calls) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "agendar",
                        {
                            "fecha_hora": "2090-01-02 12:00",
                            "servicio": "corte normal",
                            "nombre": "Obed",
                            "barbero": "Yadier",
                        },
                        "unexpected-book",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(tasks.STAFF_HELP_REPLY)])

    get_agent.cache_clear()
    with get_agent().override(model=FunctionModel(response)):
        assert tasks._run_agent(db, OBED, "Agendar cita") == tasks.STAFF_HELP_REPLY
    assert len(calls) == 2
    assert db.scalar(select(Appointment)) is None
    assert db.scalar(select(PendingAction)) is None


def test_owner_never_escalates_to_himself(staff, db, monkeypatch):
    notify = Mock()
    monkeypatch.setattr(tools, "notify_human", notify)
    ctx = SimpleNamespace(
        deps=BotDeps(wa_id=OWNER, db=db, user_message="Quiero hablar con el dueño")
    )
    assert "número es del dueño" in tools.escalar_humano(ctx, "Quiero hablar con el dueño")
    notify.assert_not_called()
