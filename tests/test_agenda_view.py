from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import agenda
from app.config import get_settings
from app.main import app
from app.store.models import Appointment, Base

NOW = datetime(2026, 10, 24, 9, 0)


class Elements(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.elements = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def role(self, role):
        return [attrs for _, attrs in self.elements if attrs.get("role") == role]


def row(id=1, **values):
    return Appointment(
        **{
            "id": id,
            "wa_id": "526140000001",
            "customer_name": "ana del rio",
            "service": "corte clasico",
            "barber": "Obed",
            "status": "confirmed",
            "starts_at": NOW + timedelta(hours=1),
            **values,
        }
    )


def test_seven_accessible_days_with_single_initial_selection():
    markup = agenda.render_agenda([row()], "all", NOW)
    document = Elements(markup)
    tabs, panels = document.role("tab"), document.role("tabpanel")
    assert len(tabs) == len(panels) == 7
    assert sum(tab["aria-selected"] == "true" for tab in tabs) == 1
    assert sum("hidden" not in panel for panel in panels) == 1
    assert {tab["aria-controls"] for tab in tabs} == {panel["id"] for panel in panels}
    assert "has-appointments" in tabs[0]["class"]
    assert all("has-appointments" not in tab["class"] for tab in tabs[1:])
    assert markup.count("<h1>Agenda</h1>") == 1
    assert "1 cita próxima" in markup and "1 citas" not in markup
    assert "Ana Del Rio" in markup and "Corte Clasico" in markup
    assert "Sin citas este día" in markup


def test_empty_and_plural_summaries():
    assert "0 citas próximas" in agenda.render_agenda([], "all", NOW)
    assert "2 citas próximas" in agenda.render_agenda([row(), row(id=2)], "all", NOW)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (datetime(2026, 10, 29), datetime(2026, 11, 4), "29 de octubre al 4 de noviembre de 2026"),
        (
            datetime(2026, 12, 29),
            datetime(2027, 1, 4),
            "29 de diciembre de 2026 al 4 de enero de 2027",
        ),
    ],
)
def test_date_range_across_month_and_year(start, end, expected):
    assert agenda._date_range(start.date(), end.date()) == expected


def test_customer_data_is_escaped_and_does_not_change_assets_or_templates():
    markup = agenda.render_agenda(
        [row(customer_name='<script>alert("x")</script>', service="<img src=x>", barber="<svg>")],
        "all",
        NOW,
    )
    assert "&lt;Script&gt;" in markup
    assert "&lt;Img Src=X&gt;" in markup
    assert "&lt;svg&gt;" in markup
    assert "<script>alert" not in markup.lower()
    assert "<img src=" not in markup.lower()
    assert "barber-unassigned" in markup
    assert 'href="https://' not in markup
    assert 'src="https://' not in markup


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("confirmed", "Confirmada"),
        ("cancelled", "Cancelada"),
        ("completed", "Completada"),
    ],
)
def test_status_labels_and_colors_use_known_classes(status, label):
    markup = agenda._format_row(row(status=status))
    assert f'data-status="{status}"' in markup
    assert label in markup
    assert "barber-obed" in markup


def test_invalid_token_never_queries_database(monkeypatch):
    def forbidden():
        raise AssertionError("Invalid token must not access appointments")

    monkeypatch.setattr(agenda, "get_session", forbidden)
    response = agenda.agenda_page("invalid")
    assert response.status_code == 403
    assert "Este enlace ya no está disponible" in response.body.decode()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("scope", ["owner", "barber"])
def test_route_preserves_staff_scope_and_future_confirmed_selection(monkeypatch, scope):
    monkeypatch.setenv("OWNER_WA_ID", "6140000000")
    monkeypatch.setenv("BARBER_OBED_WA_ID", "6141111111")
    get_settings.cache_clear()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(agenda, "datetime", Clock)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all(
        [
            row(1, customer_name="Visible Obed"),
            row(2, customer_name="Visible Yadier", barber="Yadier"),
            row(3, customer_name="Pasada", starts_at=NOW - timedelta(hours=1)),
            row(4, customer_name="Cancelada Oculta", status="cancelled"),
            row(5, customer_name="Semana Siguiente", starts_at=NOW + timedelta(days=7)),
        ]
    )
    session.commit()
    monkeypatch.setattr(agenda, "get_session", lambda: session)
    wa_id = "6140000000" if scope == "owner" else "6141111111"
    token = parse_qs(urlparse(agenda.create_agenda_link(wa_id)).query)["token"][0]
    try:
        response = agenda.agenda_page(token)
        markup = response.body.decode()
        assert response.status_code == 200
        assert "Visible Obed" in markup
        assert ("Visible Yadier" in markup) == (scope == "owner")
        for name in ("Pasada", "Cancelada Oculta", "Semana Siguiente"):
            assert name not in markup
        assert response.headers["cache-control"] == "no-store"
    finally:
        session.close()
        engine.dispose()


def test_local_assets_served_by_production_app():
    with TestClient(app, backend="asyncio") as client:
        for path in (
            "agenda.css",
            "agenda.js",
            "icons.svg",
            "fonts/inter.woff2",
            "fonts/fraunces.woff2",
        ):
            response = client.get(f"/agenda-assets/{path}")
            assert response.status_code == 200, path
            assert len(response.content) > 100
        css = client.get("/agenda-assets/agenda.css").text
        assert "inter.woff2" in css and "fraunces.woff2" in css
        assert "fonts.googleapis" not in css
