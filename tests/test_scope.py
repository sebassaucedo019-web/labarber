from app.scope import is_business_message


def test_ignores_unrelated_homework() -> None:
    assert not is_business_message("Ayúdame con mi tarea de matemáticas")
    assert not is_business_message("5x5")


def test_allows_barber_messages_and_greetings() -> None:
    assert is_business_message("Hola")
    assert is_business_message("Quiero agendar un corte para mañana")
    assert is_business_message("¿Cuánto cuesta la barba y corte?")
    assert is_business_message("¿Cuánto sale?")
    assert is_business_message("¿Dónde están y a qué hora atienden?")
    assert is_business_message("¿Tienen espacio a las 5?")
    assert is_business_message("Sí")


def test_business_context_wins_when_word_is_ambiguous() -> None:
    assert is_business_message("¿Qué hora tienen disponible para mi cita?")
    assert is_business_message("¿Me pueden confirmar para las 5?")
    assert is_business_message("La otra a nombre de Totopo para el viernes mejor")


def test_rejects_unrelated_questions_beyond_math() -> None:
    assert not is_business_message("¿Qué clima habrá mañana?")
    assert not is_business_message("¿Quién ganó el partido?")
    assert not is_business_message("¿Me traduces esto al inglés?")
