"""Local visual preview with synthetic appointments, no credentials or live database.

Run from the repository: python -m scripts.preview_agenda --port 8971
"""

import argparse
from datetime import datetime, timedelta
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import config


def create_preview() -> FastAPI:
    settings = config.Settings(
        _env_file=None,
        meta_app_secret="preview-only",
        meta_webhook_verify_token="preview-only",
        whatsapp_phone_number_id="preview-only",
        whatsapp_access_token="preview-only",
        openai_api_key="preview-only",
        openai_model="preview-only",
        database_url="sqlite:///:memory:",
        redis_url="redis://127.0.0.1:6379/15",
        owner_wa_id=None,
        barber_obed_wa_id=None,
        barber_jesus_wa_id=None,
        barber_yadier_wa_id=None,
        groq_api_key=None,
        crm_webhook_url=None,
        escalation_webhook_url=None,
        public_base_url="http://127.0.0.1",
    )
    # Isolate the renderer's import-time database setup from local .env settings.
    with patch.object(config, "get_settings", return_value=settings):
        from app import agenda

    from app.store.models import Appointment

    preview = FastAPI(
        title="BARBER CG - agenda con datos de muestra", docs_url=None, redoc_url=None
    )
    preview.mount("/agenda-assets", StaticFiles(directory=agenda.ASSET_DIR))

    @preview.get("/", response_class=HTMLResponse)
    def index(scope: str = "all", empty: bool = False):
        now = datetime.now(agenda.BUSINESS_TZ).replace(
            hour=9,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=None,
        )
        examples = [
            (0, 10, 0, "roberto mendez", "corte clasico", "Obed"),
            (0, 11, 30, "sergio anchondo", "barba y corte", "Jesús"),
            (0, 13, 0, "daniel corral", "servicio completo", "Yadier"),
            (1, 9, 30, "marco rodriguez", "corte normal", "Obed"),
            (1, 12, 0, "miguel angel fernandez de la cruz", "barba y corte", "Jesús"),
            (3, 17, 0, "alejandro", "corte clasico", "Yadier"),
            (4, 10, 0, "sofia", "corte normal", "Obed"),
            (6, 16, 30, "gonzalo", "servicio completo", "Jesús"),
        ]
        rows = [
            Appointment(
                id=index,
                wa_id="preview-only",
                customer_name=name,
                service=service,
                barber=barber,
                status="confirmed",
                starts_at=(now + timedelta(days=day)).replace(hour=hour, minute=minute),
            )
            for index, (day, hour, minute, name, service, barber) in enumerate(examples, start=1)
            if scope == "all" or scope == barber
        ]
        return agenda._html_response(agenda.render_agenda([] if empty else rows, scope, now))

    @preview.get("/expired", response_class=HTMLResponse)
    def expired():
        return agenda.agenda_page("invalid")

    return preview


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8971)
    args = parser.parse_args()
    print("Vista previa local. Todas las citas son ficticias.", flush=True)
    uvicorn.run(create_preview(), host="127.0.0.1", port=args.port, access_log=False)
