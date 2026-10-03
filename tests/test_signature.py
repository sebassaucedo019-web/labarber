import hashlib
import hmac

from app.webhook.signature import is_valid_signature


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_valid_signature_accepted() -> None:
    payload = b'{"hello": "world"}'
    secret = "shh"
    header = _sign(payload, secret)
    assert is_valid_signature(payload, header, secret) is True


def test_invalid_signature_rejected() -> None:
    payload = b'{"hello": "world"}'
    assert is_valid_signature(payload, "sha256=deadbeef", "shh") is False


def test_missing_signature_rejected() -> None:
    assert is_valid_signature(b"{}", None, "shh") is False


def test_wrong_prefix_rejected() -> None:
    assert is_valid_signature(b"{}", "sha1=abcd", "shh") is False
