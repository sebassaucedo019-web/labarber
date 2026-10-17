from app import escalation


def test_off_topic_message_is_not_a_real_escalation() -> None:
    assert escalation._REAL_ESCALATION_RE.search("El clima de hoy") is None
    assert escalation._REAL_ESCALATION_RE.search("Ayúdame con mi tarea") is None
    assert escalation._REAL_ESCALATION_RE.search("Gente pendeja") is None


def test_real_support_requests_are_escalated() -> None:
    assert escalation._REAL_ESCALATION_RE.search("Quiero hablar con una persona")
    assert escalation._REAL_ESCALATION_RE.search("Tengo un problema con mi cita")
