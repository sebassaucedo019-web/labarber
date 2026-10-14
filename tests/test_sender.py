from app.sender import _meta_recipient_id


def test_meta_recipient_id_normalizes_mexican_numbers() -> None:
    assert _meta_recipient_id("6143649949") == "526143649949"
    assert _meta_recipient_id("+52 614 364 9949") == "526143649949"
    assert _meta_recipient_id("5216143649949") == "526143649949"
