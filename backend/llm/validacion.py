"""Chequeos sobre la salida del LLM. Registran, nunca corrigen.

Si el código reescribiera la salida en silencio, no habría forma de medir
cuánto se equivoca el modelo. Cada regla del prompt que se puede verificar
en código tiene aquí su chequeo; las violaciones se guardan junto a la
extracción y se cuentan en el resumen de la etapa.
"""

# Los campos que admiten "no informa". Cuántos salieron informados mide qué
# tan rica fue la conversación, sin depender de la autoevaluación del modelo.
CAMPOS_CLAVE = [
    "forma_pago",
    "manifesto_cuota_inicial",
    "pidio_cita",
    "pidio_cotizacion",
    "intencion_declarada",
]


def mensajes_del_cliente(texto_conversacion: str) -> list[str]:
    """Extrae los mensajes del cliente de la transcripción que arma extract_ai."""
    marca = "] cliente: "
    return [linea.split(marca, 1)[1] for linea in texto_conversacion.splitlines() if marca in linea]


def campos_informados(payload: dict) -> int:
    return sum(1 for campo in CAMPOS_CLAVE if payload[campo].upper() != "NO_INFORMA")


def violaciones_consistencia(payload: dict, texto_conversacion: str) -> list[str]:
    violaciones: list[str] = []
    contado = payload["forma_pago"] == "contado"
    manifesto = payload["manifesto_cuota_inicial"]
    monto = payload["cuota_inicial_cop"]

    if contado and (manifesto != "NO_INFORMA" or monto is not None):
        violaciones.append("contado_con_cuota_inicial")
    # Desde extraccion_v5, una cifra de cero es NO y el monto se conserva
    # literal como 0. Cualquier otro monto sin SI es una contradicción.
    if manifesto != "SI" and monto is not None and not (manifesto == "NO" and monto == 0):
        violaciones.append("monto_sin_manifestar_inicial")
    if manifesto == "SI" and monto == 0:
        violaciones.append("inicial_cero_marcada_como_si")
    # Inicial mencionada con forma_pago = no_informa ya no es violación: el
    # score la resuelve como regla derivada y visible (forma_pago_para_score).

    mensajes = mensajes_del_cliente(texto_conversacion)
    fragmentos = [f.strip() for f in payload["justificacion"].split("|") if f.strip()]
    if any(not any(fragmento in mensaje for mensaje in mensajes) for fragmento in fragmentos):
        violaciones.append("justificacion_no_literal_del_cliente")
    return violaciones
