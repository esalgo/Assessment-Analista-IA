"""Etapa normalize: de raw_leads y raw_conversaciones a leads, conversaciones y mensajes.

Orden dentro de la etapa, todo en una transacción:
1. Filas con lead_id repetido e idéntico -> cuarentena (se conserva la primera).
2. Ventana de fechas y FECHA_REFERENCIA, calculadas desde las fechas inequívocas.
3. Filas que no son un lead utilizable (fecha_registro imposible, canal nulo) -> cuarentena.
4. Resto: teléfono, nombre, canal, estado, ciudad y fechas en cascada -> upsert en leads.
5. Conversaciones cuyo lead existe -> upsert; huérfanas -> cuarentena.

La cuarentena de esta etapa se borra y se reescribe en cada corrida: refleja
siempre el estado de la última ejecución.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from backend.catalogos import CANALES, CIUDADES, ESTADOS, clave
from backend.config import fecha_referencia_configurada
from backend.db.conexion import conectar

ETAPA = "normalize"
ZONA = ZoneInfo("America/Bogota")

# Margen bajo la fecha inequívoca más antigua. En este dataset cualquier
# valor entre 0 y 7 días da el mismo resultado; el margen solo evita
# descartar un lead registrado justo antes del primer dato inequívoco.
# Arriba no hay margen: nada puede ser posterior a FECHA_REFERENCIA.
MARGEN_VENTANA = timedelta(days=7)

FORMATO_SIN_HORA = "%d-%m-%Y"
FORMATOS_INEQUIVOCOS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", FORMATO_SIN_HORA)
# dd/mm primero: si ninguna regla decide, gana dd/mm porque es el formato
# mayoritario entre las fechas inequívocas con barra del archivo (204 contra
# 59 en fecha_registro). El argumento sale de los datos, no de la convención local.
FORMATOS_BARRA = ("%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M")


class ErrorDeCatalogo(Exception):
    """Un valor no está en backend/catalogos.py. Se aborta en lugar de
    adivinar: hay que agregar la variante al catálogo."""


# --- Funciones puras -------------------------------------------------------

def normalizar_telefono(texto: str) -> str | None:
    """10 dígitos, o None si no es recuperable."""
    digitos = re.sub(r"\D", "", texto)
    if len(digitos) == 12 and digitos.startswith("57"):
        digitos = digitos[2:]
    return digitos if len(digitos) == 10 else None


def normalizar_nombre(texto: str) -> str:
    return " ".join(texto.split()).title()


def vacio_a_none(texto: str) -> str | None:
    limpio = texto.strip()
    return limpio or None


def normalizar_estado(texto: str) -> str:
    estado = ESTADOS.get(clave(texto))
    if estado is None:
        raise ErrorDeCatalogo(f"estado_gestion desconocido: {texto!r}")
    return estado


def normalizar_ciudad(texto: str) -> str | None:
    if not texto.strip():
        return None
    ciudad = CIUDADES.get(clave(texto))
    if ciudad is None:
        raise ErrorDeCatalogo(f"ciudad desconocida: {texto!r}")
    return ciudad


def lecturas_fecha(texto: str) -> list[datetime] | None:
    """Todas las lecturas posibles del texto.

    None: campo vacío. []: no se puede leer (p. ej. día 33).
    Una lectura: formato inequívoco, incluido xx/xx con día > 12 o día == mes.
    Dos lecturas: xx/xx/yyyy con ambos campos <= 12, en orden (dd/mm, mm/dd).
    """
    limpio = texto.strip()
    if not limpio:
        return None
    for formato in FORMATOS_INEQUIVOCOS:
        try:
            return [datetime.strptime(limpio, formato).replace(tzinfo=ZONA)]
        except ValueError:
            pass
    lecturas: list[datetime] = []
    for formato in FORMATOS_BARRA:
        try:
            lectura = datetime.strptime(limpio, formato).replace(tzinfo=ZONA)
        except ValueError:
            continue
        if lectura not in lecturas:
            lecturas.append(lectura)
    return lecturas


def es_fecha_sin_hora(texto: str) -> bool:
    """True si el texto es dd-mm-yyyy: la hora 00:00 que produce el parser no es un dato."""
    try:
        datetime.strptime(texto.strip(), FORMATO_SIN_HORA)
    except ValueError:
        return False
    return True


def contacto_no_antes_de(contacto: datetime, contacto_sin_hora: bool, registro: datetime) -> bool:
    """Un lead no se contacta antes de existir. Si el contacto no trae hora,
    se compara por día de calendario: el mismo día nunca cuenta como antes."""
    if contacto_sin_hora:
        return contacto.date() >= registro.date()
    return contacto >= registro


@dataclass
class FechaResuelta:
    valor: datetime
    metodo: str
    ambigua: bool


def _en_ventana(fecha: datetime, ventana: tuple[date, date]) -> bool:
    return ventana[0] <= fecha.date() <= ventana[1]


def resolver_registro(
    lecturas: list[datetime],
    ventana: tuple[date, date],
    contacto_inequivoco: datetime | None = None,
    contacto_sin_hora: bool = False,
) -> FechaResuelta:
    """`lecturas` debe tener al menos un elemento.

    `contacto_inequivoco` solo se pasa si el contacto admite una sola lectura:
    un contacto ambiguo se resuelve a partir del registro y sería circular.
    """
    if len(lecturas) == 1:
        return FechaResuelta(lecturas[0], "formato_inequivoco", False)
    en_ventana = [f for f in lecturas if _en_ventana(f, ventana)]
    if len(en_ventana) == 1:
        return FechaResuelta(en_ventana[0], "ventana", False)
    if contacto_inequivoco is not None:
        candidatas = en_ventana or lecturas
        compatibles = [
            f for f in candidatas if contacto_no_antes_de(contacto_inequivoco, contacto_sin_hora, f)
        ]
        if len(compatibles) == 1:
            return FechaResuelta(compatibles[0], "coherencia", False)
    return FechaResuelta(lecturas[0], "irresoluble_ddmm", True)


def resolver_contacto(
    lecturas: list[datetime], registro: datetime, ventana: tuple[date, date]
) -> FechaResuelta:
    """`lecturas` debe tener al menos un elemento."""
    if len(lecturas) == 1:
        return FechaResuelta(lecturas[0], "formato_inequivoco", False)
    en_ventana = [f for f in lecturas if _en_ventana(f, ventana)]
    if len(en_ventana) == 1:
        return FechaResuelta(en_ventana[0], "ventana", False)
    coherentes = [f for f in en_ventana if f >= registro]
    if len(coherentes) == 1:
        return FechaResuelta(coherentes[0], "coherencia", False)
    if len(coherentes) == 2:
        mas_cercana = min(coherentes, key=lambda f: f - registro)
        return FechaResuelta(mas_cercana, "mas_cercana", True)
    return FechaResuelta(lecturas[0], "irresoluble_ddmm", True)


def calcular_ventana(textos_fecha: list[str]) -> tuple[tuple[date, date], date]:
    """Devuelve ((desde, hasta), fecha_referencia) a partir de las fechas inequívocas."""
    inequivocas = []
    for texto in textos_fecha:
        lecturas = lecturas_fecha(texto)
        if lecturas and len(lecturas) == 1:
            inequivocas.append(lecturas[0].date())
    referencia = fecha_referencia_configurada() or max(inequivocas)
    return (min(inequivocas) - MARGEN_VENTANA, referencia), referencia


# --- Base de datos ---------------------------------------------------------

COLUMNAS_RAW = (
    "lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id",
    "nombre_cliente", "telefono", "email", "ciudad", "modelo_interes_texto",
    "estado_gestion", "fecha_primer_contacto", "campania",
)

SQL_UPSERT_LEAD = """
INSERT INTO leads (
    lead_id, empresa_id, punto_venta_id, fecha_registro, fecha_registro_metodo,
    fecha_registro_ambigua, canal, nombre_cliente, telefono_normalizado, telefono_valido,
    email, ciudad, modelo_interes_texto, estado_gestion, fecha_primer_contacto,
    fecha_contacto_metodo, fecha_contacto_ambigua, fecha_contacto_sin_hora, contacto_antes_registro,
    estado_sin_contacto, campania
) VALUES (
    %(lead_id)s, %(empresa_id)s, %(punto_venta_id)s, %(fecha_registro)s, %(fecha_registro_metodo)s,
    %(fecha_registro_ambigua)s, %(canal)s, %(nombre_cliente)s, %(telefono_normalizado)s, %(telefono_valido)s,
    %(email)s, %(ciudad)s, %(modelo_interes_texto)s, %(estado_gestion)s, %(fecha_primer_contacto)s,
    %(fecha_contacto_metodo)s, %(fecha_contacto_ambigua)s, %(fecha_contacto_sin_hora)s, %(contacto_antes_registro)s,
    %(estado_sin_contacto)s, %(campania)s
)
ON CONFLICT (lead_id) DO UPDATE SET
    empresa_id = EXCLUDED.empresa_id,
    punto_venta_id = EXCLUDED.punto_venta_id,
    fecha_registro = EXCLUDED.fecha_registro,
    fecha_registro_metodo = EXCLUDED.fecha_registro_metodo,
    fecha_registro_ambigua = EXCLUDED.fecha_registro_ambigua,
    canal = EXCLUDED.canal,
    nombre_cliente = EXCLUDED.nombre_cliente,
    telefono_normalizado = EXCLUDED.telefono_normalizado,
    telefono_valido = EXCLUDED.telefono_valido,
    email = EXCLUDED.email,
    ciudad = EXCLUDED.ciudad,
    modelo_interes_texto = EXCLUDED.modelo_interes_texto,
    estado_gestion = EXCLUDED.estado_gestion,
    fecha_primer_contacto = EXCLUDED.fecha_primer_contacto,
    fecha_contacto_metodo = EXCLUDED.fecha_contacto_metodo,
    fecha_contacto_ambigua = EXCLUDED.fecha_contacto_ambigua,
    fecha_contacto_sin_hora = EXCLUDED.fecha_contacto_sin_hora,
    contacto_antes_registro = EXCLUDED.contacto_antes_registro,
    estado_sin_contacto = EXCLUDED.estado_sin_contacto,
    campania = EXCLUDED.campania
"""
# Las columnas de resolve-models (sku, marca, match_*) y de dedupe
# (cliente_id, lead_canonico_id, motivo_fusion, canales) no se tocan aquí.


def _a_cuarentena(
    conn: psycopg.Connection, origen: str, clave_fila: str, motivo: str, payload: dict
) -> None:
    conn.execute(
        """
        INSERT INTO cuarentena (etapa, origen, clave, motivo, payload)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (etapa, origen, clave, motivo) DO NOTHING
        """,
        (ETAPA, origen, clave_fila, motivo, json.dumps(payload, ensure_ascii=False)),
    )


def _normalizar_fila(
    fila: dict, registro: FechaResuelta, ventana: tuple[date, date], resumen: Counter
) -> dict:
    telefono = normalizar_telefono(fila["telefono"])
    estado = normalizar_estado(fila["estado_gestion"])

    lecturas_contacto = lecturas_fecha(fila["fecha_primer_contacto"])
    contacto_sin_hora = es_fecha_sin_hora(fila["fecha_primer_contacto"])
    contacto: FechaResuelta | None = None
    if lecturas_contacto:
        contacto = resolver_contacto(lecturas_contacto, registro.valor, ventana)
    elif lecturas_contacto == []:
        # Un contacto ilegible no invalida el lead: se cuenta y se guarda como nulo.
        resumen["fecha_contacto_imposible"] += 1

    resumen[f"fecha_registro_{registro.metodo}"] += 1
    if contacto:
        resumen[f"fecha_contacto_{contacto.metodo}"] += 1
    if telefono is None:
        resumen["telefono_invalido"] += 1

    return {
        "lead_id": fila["lead_id"],
        "empresa_id": fila["empresa_id"],
        "punto_venta_id": fila["punto_venta_id"],
        "fecha_registro": registro.valor,
        "fecha_registro_metodo": registro.metodo,
        "fecha_registro_ambigua": registro.ambigua,
        "canal": CANALES[clave(fila["canal"])],
        "nombre_cliente": normalizar_nombre(fila["nombre_cliente"]),
        "telefono_normalizado": telefono,
        "telefono_valido": telefono is not None,
        "email": vacio_a_none(fila["email"]),
        "ciudad": normalizar_ciudad(fila["ciudad"]),
        "modelo_interes_texto": vacio_a_none(fila["modelo_interes_texto"]),
        "estado_gestion": estado,
        "fecha_primer_contacto": contacto.valor if contacto else None,
        "fecha_contacto_metodo": contacto.metodo if contacto else None,
        "fecha_contacto_ambigua": contacto.ambigua if contacto else False,
        "fecha_contacto_sin_hora": contacto_sin_hora,
        "contacto_antes_registro": bool(
            contacto and not contacto_no_antes_de(contacto.valor, contacto_sin_hora, registro.valor)
        ),
        "estado_sin_contacto": estado != "sin_gestion" and contacto is None,
        "campania": vacio_a_none(fila["campania"]),
    }


def _normalizar_leads(conn: psycopg.Connection, resultado: "ResultadoNormalize") -> dict[str, str]:
    """Devuelve {lead_id: empresa_id} de los leads cargados."""
    resumen = resultado.conteos
    with conn.cursor(row_factory=dict_row) as cur:
        filas = cur.execute(
            f"SELECT fila_num, {', '.join(COLUMNAS_RAW)} FROM raw_leads ORDER BY fila_num"
        ).fetchall()
    resumen["leads_leidos"] = len(filas)

    primera_por_lead: dict[str, dict] = {}
    unicas: list[dict] = []
    for fila in filas:
        previa = primera_por_lead.get(fila["lead_id"])
        if previa is None:
            primera_por_lead[fila["lead_id"]] = fila
            unicas.append(fila)
            continue
        identica = all(fila[c] == previa[c] for c in COLUMNAS_RAW)
        motivo = (
            f"copia idéntica de la fila {previa['fila_num']}" if identica
            else f"lead_id repetido con contenido distinto a la fila {previa['fila_num']}"
        )
        _a_cuarentena(conn, "leads.csv", f"{fila['lead_id']} (fila {fila['fila_num']})", motivo, fila)
        resumen["cuarentena_lead_id_repetido"] += 1

    ventana, referencia = calcular_ventana(
        [f["fecha_registro"] for f in unicas] + [f["fecha_primer_contacto"] for f in unicas]
    )
    resultado.ventana = ventana
    resultado.fecha_referencia = referencia

    empresa_por_lead: dict[str, str] = {}
    for fila in unicas:
        motivos = []
        lecturas_registro = lecturas_fecha(fila["fecha_registro"])
        if lecturas_registro is None:
            motivos.append("fecha_registro nula")
        elif lecturas_registro == []:
            motivos.append(f"fecha_registro imposible: {fila['fecha_registro'].strip()}")
        texto_canal = fila["canal"].strip()
        if not texto_canal:
            motivos.append("canal nulo")
        elif clave(texto_canal) not in CANALES:
            motivos.append(f"canal desconocido: {texto_canal}")

        if motivos:
            for motivo in motivos:
                _a_cuarentena(conn, "leads.csv", fila["lead_id"], motivo, fila)
            resumen["cuarentena_lead_no_utilizable"] += 1
            continue

        assert lecturas_registro
        lecturas_contacto = lecturas_fecha(fila["fecha_primer_contacto"])
        contacto_inequivoco = lecturas_contacto[0] if lecturas_contacto and len(lecturas_contacto) == 1 else None
        registro = resolver_registro(
            lecturas_registro, ventana, contacto_inequivoco, es_fecha_sin_hora(fila["fecha_primer_contacto"])
        )
        lead = _normalizar_fila(fila, registro, ventana, resumen)
        conn.execute(SQL_UPSERT_LEAD, lead)
        empresa_por_lead[lead["lead_id"]] = lead["empresa_id"]

        resumen["contacto_antes_registro"] += lead["contacto_antes_registro"]
        resumen["fecha_contacto_sin_hora"] += lead["fecha_contacto_sin_hora"]
        resumen["estado_sin_contacto"] += lead["estado_sin_contacto"]

    resumen["leads_cargados"] = len(empresa_por_lead)
    return empresa_por_lead


def _normalizar_conversaciones(
    conn: psycopg.Connection, empresa_por_lead: dict[str, str], resumen: Counter
) -> None:
    filas = conn.execute("SELECT payload FROM raw_conversaciones ORDER BY fila_num").fetchall()
    resumen["conversaciones_leidas"] = len(filas)

    for (conversacion,) in filas:
        conversacion_id = conversacion["conversacion_id"]
        lead_id = conversacion["lead_id"]
        empresa_id = empresa_por_lead.get(lead_id)
        if empresa_id is None:
            _a_cuarentena(
                conn, "conversaciones.json", conversacion_id,
                f"lead_id inexistente: {lead_id}", conversacion,
            )
            resumen["cuarentena_conversacion_huerfana"] += 1
            continue

        # El canal de la conversación (WhatsApp) puede diferir del canal del
        # lead: es la señal multicanal, no un error. Se guardan ambos tal cual.
        conn.execute(
            """
            INSERT INTO conversaciones (conversacion_id, lead_id, empresa_id, canal, fecha_inicio)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (conversacion_id) DO UPDATE SET
                lead_id = EXCLUDED.lead_id,
                empresa_id = EXCLUDED.empresa_id,
                canal = EXCLUDED.canal,
                fecha_inicio = EXCLUDED.fecha_inicio
            """,
            (
                conversacion_id, lead_id, empresa_id, conversacion["canal"],
                datetime.strptime(conversacion["fecha_inicio"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZONA),
            ),
        )
        # Los mensajes se reemplazan enteros: si el archivo trae menos, no quedan sobrantes.
        conn.execute("DELETE FROM mensajes WHERE conversacion_id = %s", (conversacion_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO mensajes (conversacion_id, orden, empresa_id, emisor, hora, texto)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (conversacion_id, orden, empresa_id, m["emisor"], time.fromisoformat(m["hora"]), m["texto"])
                    for orden, m in enumerate(conversacion["mensajes"], start=1)
                ],
            )
        resumen["conversaciones_cargadas"] += 1
        resumen["mensajes_cargados"] += len(conversacion["mensajes"])


@dataclass
class ResultadoNormalize:
    conteos: Counter
    ventana: tuple[date, date] | None = None
    fecha_referencia: date | None = None


def normalizar() -> ResultadoNormalize:
    resultado = ResultadoNormalize(conteos=Counter())
    with conectar() as conn, conn.transaction():
        conn.execute("DELETE FROM cuarentena WHERE etapa = %s", (ETAPA,))
        empresa_por_lead = _normalizar_leads(conn, resultado)
        _normalizar_conversaciones(conn, empresa_por_lead, resultado.conteos)
    return resultado
