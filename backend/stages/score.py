"""Etapa score: puntaje 0-100 por cliente (grupo fusionado), con sus factores.

Dos componentes con respaldo distinto (docs/validacion.md, sección 2):
1. Señales de la conversación: puntos de la regresión (config/score_weights.json).
2. Urgencia: multiplicador por tramo de horas sin contacto, derivado de la
   tabla de tasas del histórico. Solo aplica a clientes todavía sin contacto.

Un cliente es el grupo fusionado (canónico + absorbidos): el score se
calcula sobre el grupo consolidado, no sobre el canónico solo.

Reglas derivadas: no modifican la salida del LLM guardada en extracciones_ia.
Calculan el valor que usa el score y devuelven el nombre de la regla aplicada,
para que quede en los factores y el tablero pueda mostrarla.

Colas. Priorizar no es predecir: los tramos de urgencia son correctos sobre
probabilidad de cierre, pero en un orden global mandan al final a los clientes
que nadie ha tocado. Por eso hay dos colas con su propia capacidad:
- primer_contacto: nadie del grupo ha sido contactado.
- seguimiento: ya contactados.
Cada cola se ordena por score y desempata por horas transcurridas, lo más
fresco primero. Quién se atiende hoy lo decide assign con la capacidad de cada
punto de venta. La temperatura describe la calidad del lead según sus señales.
"""

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time

import psycopg

from backend.config import RAIZ, fecha_referencia_configurada
from backend.db.conexion import conectar
from backend.stages.normalize import ZONA

RUTA_PESOS = RAIZ / "config" / "score_weights.json"
PROMPT_VERSION = "extraccion_v5"
REGLA_INICIAL_IMPLICA_CREDITO = "inicial_mencionada_implica_credito"
VARIABLES_CONVERSACION = ["pidio_cita", "manifesto_cuota_inicial", "forma_pago"]

# Embudo, de menos a más avanzado. descartado no está: es una salida, no un avance.
EMBUDO = ["sin_gestion", "no_contesta", "contactado", "en_proceso", "cotizacion_enviada"]


def forma_pago_para_score(extraccion: dict) -> tuple[str, str | None]:
    """Si el tema de la inicial salió (SI o NO) y el LLM dejó forma_pago en
    no_informa, la forma de pago es crédito: nadie que pague de contado dice
    "no tengo inicial". Devuelve (valor, regla aplicada o None)."""
    forma_pago = extraccion["forma_pago"]
    if forma_pago == "no_informa" and extraccion["manifesto_cuota_inicial"] in ("SI", "NO"):
        return "credito", REGLA_INICIAL_IMPLICA_CREDITO
    return forma_pago, None


# --- Consolidación del grupo fusionado ---------------------------------------


def estado_consolidado(estados: list[tuple[datetime, str]]) -> str:
    """(fecha_registro, estado) de cada lead del grupo.

    - Gana el estado más avanzado del embudo.
    - descartado vale solo si es el estado más reciente del grupo; si hay un
      registro posterior, la persona volvió y vale el estado del embudo.
    - "Más reciente" usa fecha_registro como sustituta: los datos no traen la
      fecha del cambio de estado (supuesto declarado en el README).
    """
    ordenados = sorted(estados)
    if ordenados[-1][1] == "descartado":
        return "descartado"
    en_embudo = [estado for _, estado in ordenados if estado != "descartado"]
    return max(en_embudo, key=EMBUDO.index)


def punto_venta_del_grupo(leads: list[tuple[datetime, str, str]]) -> str:
    """(fecha_registro, lead_id, punto_venta_id) de cada lead del grupo.

    El punto de venta del lead más reciente, porque refleja el interés actual
    del cliente. No es el del canónico: dedupe elige como canónico el lead más
    antiguo. Desempate por lead_id, para que sea determinista."""
    return max(leads)[2]


def extraccion_consolidada(extracciones: list[tuple[datetime, dict]]) -> dict | None:
    """(fecha_registro del lead, payload) de cada lead del grupo con conversación.

    Por campo, vale el último valor informado en orden de registro: la misma
    regla del prompt ("si el cliente cambia de postura, vale lo último que
    dijo"), aplicada entre conversaciones de leads distintos del mismo cliente.
    """
    if not extracciones:
        return None
    ordenadas = [payload for _, payload in sorted(extracciones, key=lambda par: par[0])]
    consolidada = dict(ordenadas[-1])
    for campo in VARIABLES_CONVERSACION:
        informados = [p[campo] for p in ordenadas if p[campo].upper() != "NO_INFORMA"]
        consolidada[campo] = informados[-1] if informados else ordenadas[-1][campo]
    return consolidada


# --- Puntaje -----------------------------------------------------------------


def cargar_pesos() -> dict:
    return json.loads(RUTA_PESOS.read_text(encoding="utf-8"))


def puntos_conversacion(extraccion: dict | None, pesos: dict) -> tuple[int, list[dict]]:
    """Suma de puntos de las señales y la lista de factores que aportaron.
    Sin conversación no hay señales: 0 puntos, el cliente queda en la tasa base."""
    if extraccion is None:
        return 0, []
    forma_pago, regla = forma_pago_para_score(extraccion)
    valores = {
        "pidio_cita": extraccion["pidio_cita"],
        "manifesto_cuota_inicial": extraccion["manifesto_cuota_inicial"],
        "forma_pago": forma_pago,
    }
    factores = []
    for variable, valor in valores.items():
        puntos = pesos["variables"][variable][valor]
        if puntos == 0:
            continue
        factor = {"variable": variable, "valor": valor, "puntos": puntos}
        if variable == "forma_pago" and regla:
            factor["regla"] = regla
        factores.append(factor)
    return sum(f["puntos"] for f in factores), factores


def tramo_urgencia(horas_sin_contacto: float | None, pesos: dict) -> dict | None:
    """Tramo del cliente pendiente. None si ya fue contactado: la ventana del
    primer contacto ya se usó y no hay oportunidad que premiar."""
    if horas_sin_contacto is None:
        return None
    for tramo in pesos["urgencia"]["tramos"]:
        if tramo["horas_hasta"] is None or horas_sin_contacto <= tramo["horas_hasta"]:
            return tramo
    raise ValueError("los tramos de urgencia deben terminar en uno sin límite")


def log_odds_relativos(puntos: int, multiplicador: float, pesos: dict) -> float:
    """Cuánto se aleja el cliente de la tasa base, en log-odds.

    tasa del cliente = sigmoide(logit(tasa base) + puntos / 100) × multiplicador
    El resultado es logit(tasa del cliente) − logit(tasa base): 0 para un
    cliente sin señales y multiplicador 1.
    """
    base = pesos["entrenamiento"]["tasa_base"]
    logit_base = math.log(base / (1 - base))
    tasa = multiplicador / (1 + math.exp(-(logit_base + puntos / pesos["puntos_por_log_odds"])))
    return math.log(tasa / (1 - tasa)) - logit_base


def puntos_posibles(pesos: dict) -> list[int]:
    """Puntos de todas las combinaciones de señales que una extracción puede
    producir. No basta con sumar el máximo de cada variable: contado con
    manifesto_cuota_inicial = SI no puede ocurrir (con contado la inicial es
    NO_INFORMA por regla del prompt), y la regla de crédito cambia no_informa."""
    variables = pesos["variables"]
    posibles = set()
    for cita in variables["pidio_cita"]:
        for manifesto in variables["manifesto_cuota_inicial"]:
            for forma in variables["forma_pago"]:
                if forma == "contado" and manifesto != "NO_INFORMA":
                    continue
                extraccion = {"pidio_cita": cita, "manifesto_cuota_inicial": manifesto, "forma_pago": forma}
                posibles.add(puntos_conversacion(extraccion, pesos)[0])
    return sorted(posibles)


def rango_log_odds(pesos: dict) -> tuple[float, float]:
    """Extremos alcanzables: peor y mejor combinación posible de señales con
    el menor y el mayor multiplicador (1 = ya contactado)."""
    puntos = puntos_posibles(pesos)
    multiplicadores = [t["multiplicador"] for t in pesos["urgencia"]["tramos"]] + [1.0]
    return (
        log_odds_relativos(puntos[0], min(multiplicadores), pesos),
        log_odds_relativos(puntos[-1], max(multiplicadores), pesos),
    )


def a_escala_0_100(relativo: float, pesos: dict) -> int:
    """50 = tasa base. El mejor cliente posible es 100 y el peor posible 0.

    Lineal por tramos: por encima de la base se escala con el máximo
    alcanzable y por debajo con el mínimo. Sin recorte: ningún cliente
    puede salir del rango porque los extremos salen de los mismos pesos.
    """
    minimo, maximo = rango_log_odds(pesos)
    if relativo >= 0:
        return round(50 + 50 * relativo / maximo)
    return round(50 - 50 * relativo / minimo)


# --- Colas y temperatura -----------------------------------------------------

COLA_PRIMER_CONTACTO = "primer_contacto"
COLA_SEGUIMIENTO = "seguimiento"
FUERA_DE_COLA = "descartado"

# Señales positivas fuertes. contado e inicial SI no pueden coexistir, así que
# un cliente tiene como máximo dos: cita + contado o cita + inicial declarada.
SENALES_POSITIVAS = [
    ("pidio_cita", "SI"),
    ("forma_pago", "contado"),
    ("manifesto_cuota_inicial", "SI"),
]


def clave_de_orden(score: int, horas_desempate: float) -> tuple[int, float]:
    """Mayor score primero; a igual score, lo más fresco primero.

    El desempate es la urgencia en forma continua. Dentro de una cola ordena
    los empates, que son masivos (cientos de clientes con el mismo score)."""
    return (-score, horas_desempate)


def temperatura_por_senales(factores: list[dict]) -> str:
    """Calidad del lead según sus señales, independiente de la capacidad.

    alta = dos señales positivas fuertes; media = una; baja = ninguna.
    Un lead puede ser alta y no entrar hoy porque la capacidad de su punto
    de venta se llenó: eso lo decide assign, no la temperatura."""
    presentes = {(f["variable"], f["valor"]) for f in factores}
    positivas = sum(senal in presentes for senal in SENALES_POSITIVAS)
    if positivas >= 2:
        return "alta"
    if positivas == 1:
        return "media"
    return "baja"


# --- Etapa -------------------------------------------------------------------


@dataclass
class ScoreCliente:
    lead_id: str
    empresa_id: str
    punto_venta_id: str
    score: int
    puntos_conversacion: int
    multiplicador: float
    tramo_urgencia: str | None
    estado: str
    cola: str
    horas_desempate: float
    temperatura: str
    sin_senal_conversacional: bool
    factores: list[dict] = field(default_factory=list)


def fecha_referencia(conn: psycopg.Connection) -> datetime:
    """FECHA_REFERENCIA configurada (a medianoche) o la máxima fecha inequívoca
    del dataset. Nunca now(): el resultado no puede depender del día en que se corre."""
    configurada = fecha_referencia_configurada()
    if configurada:
        return datetime.combine(configurada, time.min, tzinfo=ZONA)
    return conn.execute(
        """
        SELECT greatest(
            (SELECT max(fecha_registro) FROM leads WHERE NOT fecha_registro_ambigua),
            (SELECT max(fecha_primer_contacto) FROM leads
             WHERE NOT fecha_contacto_ambigua AND NOT fecha_contacto_sin_hora)
        )
        """
    ).fetchone()[0]


def _puntuar_grupo(filas: list[tuple], referencia: datetime, pesos: dict) -> ScoreCliente:
    """filas: (grupo, lead_id, empresa_id, punto_venta_id, fecha_registro,
    estado_gestion, fecha_primer_contacto, payload), la del canónico primero."""
    canonico = filas[0]
    estado = estado_consolidado([(f[4], f[5]) for f in filas])
    contactos = [f[6] for f in filas if f[6] is not None]
    extraccion = extraccion_consolidada([(f[4], f[7]) for f in filas if f[7] is not None])

    if contactos:
        cola = COLA_SEGUIMIENTO
        # Horas desde el primer contacto del grupo: el seguimiento más reciente va primero.
        horas = (referencia - min(contactos)).total_seconds() / 3600
        tramo = None
    else:
        cola = COLA_PRIMER_CONTACTO
        horas = (referencia - min(f[4] for f in filas)).total_seconds() / 3600
        tramo = tramo_urgencia(horas, pesos)
    if estado == "descartado":
        cola = FUERA_DE_COLA
    multiplicador = tramo["multiplicador"] if tramo else 1.0

    puntos, factores = puntos_conversacion(extraccion, pesos)
    temperatura = temperatura_por_senales(factores)
    if tramo:
        factores.append({"variable": "urgencia", "valor": tramo["tramo"], "multiplicador": multiplicador})

    return ScoreCliente(
        lead_id=canonico[0],
        empresa_id=canonico[2],
        punto_venta_id=punto_venta_del_grupo([(f[4], f[1], f[3]) for f in filas]),
        score=a_escala_0_100(log_odds_relativos(puntos, multiplicador, pesos), pesos),
        puntos_conversacion=puntos,
        multiplicador=multiplicador,
        tramo_urgencia=tramo["tramo"] if tramo else None,
        estado=estado,
        cola=cola,
        horas_desempate=round(horas, 2),
        temperatura=temperatura,
        sin_senal_conversacional=extraccion is None,
        factores=factores,
    )


def calcular_scores() -> tuple[list[ScoreCliente], datetime]:
    pesos = cargar_pesos()
    with conectar() as conn:
        referencia = fecha_referencia(conn)
        leads = conn.execute(
            """
            SELECT coalesce(l.lead_canonico_id, l.lead_id) AS grupo, l.lead_id, l.empresa_id,
                   l.punto_venta_id, l.fecha_registro, l.estado_gestion, l.fecha_primer_contacto, e.payload
            FROM leads l
            LEFT JOIN extracciones_ia e ON e.lead_id = l.lead_id AND e.prompt_version = %s
            ORDER BY grupo, l.lead_canonico_id IS NOT NULL, l.fecha_registro
            """,
            (PROMPT_VERSION,),
        ).fetchall()

    grupos: dict[str, list[tuple]] = defaultdict(list)
    for fila in leads:
        grupos[fila[0]].append(fila)
    return [_puntuar_grupo(filas, referencia, pesos) for filas in grupos.values()], referencia


def guardar_scores(resultados: list[ScoreCliente]) -> None:
    """Reemplaza la tabla completa en una transacción: una fila por cliente
    (lead canónico). Así no quedan filas de leads que dejaron de ser canónicos."""
    pesos = cargar_pesos()
    with conectar() as conn, conn.transaction():
        conn.execute("DELETE FROM scores")
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO scores (lead_id, empresa_id, score, temperatura, factores,
                    sin_senal_conversacional, score_version, cola, horas_desempate, estado_consolidado,
                    punto_venta_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        r.lead_id, r.empresa_id, r.score, r.temperatura,
                        json.dumps(r.factores, ensure_ascii=False), r.sin_senal_conversacional,
                        pesos["score_version"], r.cola, r.horas_desempate, r.estado, r.punto_venta_id,
                    )
                    for r in resultados
                ],
            )
