"""Ejemplo de WhatsApp Flow: formulario de reserva (nombre, fecha, motivo).

ADVERTENCIA: la sintaxis de pywa para Flows (nombres de clases, parámetros) cambió varias
veces entre versiones y puede seguir cambiando. Esto es un boceto razonable, basado en el
patrón general de pywa (FlowJSON -> Screen -> Layout -> componentes), pero NO está
verificado línea por línea contra la versión de pywa instalada en tu proyecto. Antes de
usarlo: revisá pywa.readthedocs.io (sección Flows) y ajustá nombres de clases/parámetros
si hace falta. No es copy-paste garantizado — ver README.md de esta carpeta.
"""

from pywa.types.flows import (
    Action,
    DatePicker,
    FlowActionType,
    FlowJSON,
    Footer,
    Form,
    Layout,
    LayoutType,
    Screen,
    TextInput,
)

RESERVA_FLOW = FlowJSON(
    version="7.0",  # confirmá la versión de Flow JSON vigente en la doc de Meta
    screens=[
        Screen(
            id="RESERVA",
            title="Reservá tu turno",
            terminal=True,
            layout=Layout(
                type=LayoutType.SINGLE_COLUMN,
                children=[
                    Form(
                        name="form_reserva",
                        children=[
                            TextInput(
                                name="nombre",
                                label="Nombre completo",
                                required=True,
                            ),
                            DatePicker(
                                name="fecha",
                                label="Fecha preferida",
                                required=True,
                            ),
                            TextInput(
                                name="motivo",
                                label="Motivo de la reserva",
                                required=False,
                            ),
                            Footer(
                                label="Confirmar",
                                on_click_action=Action(
                                    name=FlowActionType.COMPLETE,
                                    payload={
                                        "nombre": "${form.nombre}",
                                        "fecha": "${form.fecha}",
                                        "motivo": "${form.motivo}",
                                    },
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        ),
    ],
)

# Este objeto es la definición del flow, no lo manda a nadie por sí solo. Para registrarlo
# en Meta y enviarlo a un usuario, ver la sección "Cómo se usa esto en la práctica" del
# README.md de esta carpeta — esa parte depende de métodos del cliente pywa
# (create_flow / send de un botón interactivo tipo flow) que preferimos no inventar acá.
