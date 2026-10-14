from app.scope import is_business_message


def test_ignores_unrelated_homework() -> None:
    assert not is_business_message("Ayúdame con mi tarea de matemáticas")
    assert not is_business_message("5x5")


def test_allows_barber_messages_and_greetings() -> None:
    assert is_business_message("Hola")
    assert is_business_message("Quiero agendar un corte para mañana")
    assert is_business_message("¿Cuánto cuesta la barba y corte?")


def test_business_context_wins_when_word_is_ambiguous() -> None:
    assert is_business_message("¿Qué hora tienen disponible para mi cita?")
