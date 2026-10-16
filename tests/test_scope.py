from app.scope import is_business_message, is_greeting
from app.agenda import is_agenda_link_request


def test_ignores_unrelated_homework() -> None:
    assert not is_business_message("Ayúdame con mi tarea de matemáticas")
    assert not is_business_message("5x5")
    assert is_greeting("Hola")
    assert not is_greeting("Hola, quiero una cita")


def test_allows_barber_messages_and_greetings() -> None:
    assert is_business_message("Hola")
    assert is_business_message("Quiero agendar un corte para mañana")
    assert is_business_message("¿Cuánto cuesta la barba y corte?")
    assert is_business_message("¿Cuánto sale?")
    assert is_business_message("¿Dónde están y a qué hora atienden?")
    assert is_business_message("¿Tienen espacio a las 5?")
    assert is_business_message("Sí")
    assert is_business_message("¿Qué cortes manejan?")
    assert is_business_message("¿Aceptan tarjeta?")
    assert is_business_message("Quiero cortarme el cabello")
    assert is_business_message("¿Me pasas la ubicación?")
    assert is_business_message("¿Cuánto tardan en atender?")
    assert is_greeting("Ola")
    assert is_greeting("Holaaa")
    assert is_greeting("Qué onda")
    assert is_greeting("Buenas noches")
    assert is_greeting("Saludos")
    assert not is_greeting("Hola, quiero agendar una cita")


def test_business_context_wins_when_word_is_ambiguous() -> None:
    assert is_business_message("¿Qué hora tienen disponible para mi cita?")
    assert is_business_message("¿Me pueden confirmar para las 5?")
    assert is_business_message("La otra a nombre de Totopo para el viernes mejor")
    assert is_business_message("5 pm", has_business_context=True)
    assert is_business_message("5 p", has_business_context=True)
    assert is_business_message("5 de la tarde", has_business_context=True)
    assert is_business_message("A nombre de Sofía", has_business_context=True)
    assert is_business_message("¿Y qué más?", has_business_context=True)
    assert is_business_message("¿Cómo le hago?", has_business_context=True)
    assert not is_business_message("Resuelve 5x5", has_business_context=True)
    assert not is_business_message("5 pm")
    assert is_business_message("Cancela las citas")
    assert is_business_message("Cancela mi cita de mañana")


def test_rejects_unrelated_questions_beyond_math() -> None:
    assert not is_business_message("¿Qué clima habrá mañana?")
    assert not is_business_message("¿Quién ganó el partido?")
    assert not is_business_message("¿Me traduces esto al inglés?")


def test_detects_staff_agenda_link_requests() -> None:
    assert is_agenda_link_request("Link")
    assert is_agenda_link_request("enlace")
    assert is_agenda_link_request("Pásame el link de mi agenda")
    assert is_agenda_link_request("Quiero ver mi agenda en el celular")
    assert is_agenda_link_request("Dame la agenda")
    assert not is_agenda_link_request("Quiero agendar una cita")
    assert not is_agenda_link_request("¿Qué servicios tienen?")
