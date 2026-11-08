"""Send an approved utility template outside a recipient's 24-hour window."""

import httpx

from app.config import get_settings
from app.safety import sanitize_reply


def send_appointment_template(
    recipient: str, message: str, *, template_name: str | None = None
) -> tuple[str, str | None]:
    settings = get_settings()
    template_name = settings.appointment_template_name if template_name is None else template_name
    if not template_name.strip():
        return "failed", "appointment_template_not_configured"
    # The approved body has one text parameter containing the immutable outbox snapshot.
    detail = " ".join(sanitize_reply(message).split())
    if len(detail) > 1000:
        return "failed", "appointment_template_text_too_long"
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": settings.notification_template_language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": detail}]}],
        },
    }
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                f"https://graph.facebook.com/v25.0/{settings.whatsapp_phone_number_id}/messages",
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                json=payload,
            )
    except httpx.RequestError:
        # A timeout does not prove rejection. Avoid duplicate notices on blind retries.
        return "uncertain", "template_submission_unknown"
    if response.status_code == 429:
        return "pending", "meta_rate_limit"
    if response.status_code >= 500:
        return "uncertain", "template_submission_unknown"
    if not response.is_success:
        return "failed", f"meta_http_{response.status_code}"
    try:
        message_id = response.json()["messages"][0]["id"]
    except (ValueError, KeyError, IndexError, TypeError):
        return "uncertain", "template_missing_receipt"
    return (
        ("sent", None)
        if isinstance(message_id, str) and message_id
        else ("uncertain", "template_missing_receipt")
    )
