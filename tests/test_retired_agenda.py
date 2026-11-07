"""The removed web UI must not survive via old routes, cookies or links."""

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from sqlalchemy import create_engine, inspect, text

from app.agent.history import trim_history
from app.main import app
from app.safety import retire_agenda_links, sanitize_reply
from app.store import postgres


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/agenda?token=legacy-token"),
        ("GET", "/panel"),
        ("GET", "/panel-sw.js"),
        ("GET", "/agenda-assets/agenda.js"),
        ("GET", "/agenda-assets/panel.webmanifest"),
        ("GET", "/api/agenda/session"),
        ("GET", "/api/agenda/calendar"),
        ("GET", "/api/agenda/notifications"),
        ("POST", "/api/agenda/login"),
        ("POST", "/api/agenda/logout"),
        ("POST", "/api/agenda/appointments/1/state"),
        ("POST", "/api/agenda/appointments/1/consent"),
        ("POST", "/api/agenda/blocks"),
        ("DELETE", "/api/agenda/blocks/1"),
    ],
)
def test_old_web_endpoints_are_unavailable_even_with_legacy_session(method, path):
    client = TestClient(app, base_url="https://testserver")
    try:
        response = client.request(
            method, path, headers={"Cookie": "__Host-waia_session=old-session"}
        )
        assert response.status_code == 404
        assert "set-cookie" not in response.headers
        assert client.get("/health").json() == {"status": "ok"}
    finally:
        client.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://labarber-production-b9de.up.railway.app/agenda?token=old-secret",
        "https://labarber-production-5c92.up.railway.app/agenda/?token=old-secret",
        "https://custom.example/panel",
        "https://custom.example/panel#dia=2026-10-24",
    ],
)
def test_retired_urls_are_removed_without_losing_confirmation(url):
    reply = "Cita confirmada para Ana a las 12:00.\n" + url
    cleaned = sanitize_reply(reply)
    assert cleaned.startswith("Cita confirmada para Ana a las 12:00.")
    assert "retirada" in cleaned and "WhatsApp" in cleaned
    assert url not in cleaned and "old-secret" not in cleaned
    assert sanitize_reply(cleaned) == cleaned


def test_other_business_urls_are_preserved():
    message = "Ubicación: https://maps.google.com/?q=barberia\nhttps://calendar.google.com/"
    assert retire_agenda_links(message) == message


def test_old_link_history_preserves_tool_pairs_and_reservation_context():
    url = "https://barber.example/agenda?token=old-secret"
    history = [
        ModelRequest(parts=[UserPromptPart("Dame mi agenda")]),
        ModelResponse(parts=[ToolCallPart("obtener_enlace_agenda", {}, "old-call")]),
        ModelRequest(parts=[ToolReturnPart("obtener_enlace_agenda", url, "old-call")]),
        ModelResponse(parts=[TextPart("Aquí está tu agenda:\n" + url)]),
        ModelRequest(parts=[UserPromptPart("¿La de Ana sigue a las 12?")]),
    ]
    trimmed = trim_history(history)
    assert len(trimmed) == len(history)
    assert trimmed[1].parts[0].tool_call_id == trimmed[2].parts[0].tool_call_id == "old-call"
    assert "retirada" in trimmed[2].parts[0].content
    assert "old-secret" not in trimmed[3].parts[0].content
    assert trimmed[-1].parts[0].content == "¿La de Ana sigue a las 12?"


def test_startup_does_not_drop_legacy_accounts_or_sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-panel.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE staff_accounts (username TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO staff_accounts VALUES ('legacy-owner')"))
        connection.execute(
            text("CREATE TABLE staff_sessions (token_hash TEXT PRIMARY KEY, username TEXT)")
        )
        connection.execute(text("INSERT INTO staff_sessions VALUES ('old-hash', 'legacy-owner')"))
    monkeypatch.setattr(postgres, "_engine", engine)
    try:
        postgres.init_db()
        postgres.init_db()
        assert "appointments" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT username FROM staff_accounts")) == "legacy-owner"
            assert connection.scalar(text("SELECT token_hash FROM staff_sessions")) == "old-hash"
    finally:
        engine.dispose()
