import hashlib
import hmac
import json

import fakeredis
import pytest
from fastapi.testclient import TestClient
from rq import Queue

from app.main import app
from app.store import redis_store
from app.webhook.normalize import extract_text_messages
from app.webhook.signature import is_valid_signature


@pytest.fixture
def client(monkeypatch):
    redis = fakeredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr(redis_store, "_client", redis)
    # Startup DB initialization is tested separately against a temporary database.
    yield TestClient(app), redis


def post(client, payload):
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=raw, headers={"x-hub-signature-256": signature})


def payload(phone_id="123456789"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_id},
                            "messages": [
                                {
                                    "from": "5216143649949",
                                    "id": "wamid.test",
                                    "type": "text",
                                    "text": {"body": "Hola"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_signed_webhook_buffers_once_and_unsigned_is_rejected(client):
    http, redis = client
    assert http.post("/webhook", json=payload()).status_code == 401
    assert post(http, payload()).status_code == 200
    assert post(http, payload()).status_code == 200
    assert Queue("agente-whatsapp", connection=redis).count == 1
    assert redis.lrange("pending:526143649949", 0, -1) == [b"Hola"]


def test_other_business_number_is_ignored(client):
    http, redis = client
    assert post(http, payload("different-number")).status_code == 200
    assert Queue("agente-whatsapp", connection=redis).count == 0


@pytest.mark.parametrize(
    "data",
    [
        {"entry": None},
        {"entry": [None]},
        {"entry": [{"changes": None}]},
        {"entry": [{"changes": [{"value": {"messages": None}}]}]},
        {"entry": [{"changes": 42}]},
    ],
)
def test_malformed_collections_do_not_crash(data):
    assert list(extract_text_messages(data)) == []


def test_verification_requires_token_and_challenge(client):
    http, _ = client
    assert (
        http.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verify-token",
                "hub.challenge": "123",
            },
        ).text
        == "123"
    )
    assert (
        http.get(
            "/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "test-verify-token"}
        ).status_code
        == 403
    )


def test_large_payload_and_non_ascii_signature_rejected(client):
    http, _ = client
    assert http.post("/webhook", content=b"x" * (1024 * 1024 + 1)).status_code == 413
    assert not is_valid_signature(b"{}", "sha256=" + "ñ" * 64, "test-secret")


def test_stable_button_id_overrides_label():
    data = payload()
    message = data["entry"][0]["changes"][0]["value"]["messages"][0]
    message.update(
        type="interactive", interactive={"button_reply": {"id": "book", "title": "Otro texto"}}
    )
    assert list(extract_text_messages(data))[0]["text"] == "Agendar cita"
