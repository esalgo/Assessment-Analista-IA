"""Etapa extract-ai: señales de compra de las conversaciones, con un LLM.

1. Por lead se concatenan sus conversaciones en orden cronológico (25 leads tienen dos).
2. hash = sha256(texto + prompt_version). Si (lead_id, hash) ya está en
   extracciones_ia, ese lead no se envía: reejecutar no paga tokens.
3. Los pendientes se envían en paralelo, como máximo LLM_CONCURRENCIA a la vez.
4. Cada respuesta se guarda apenas llega: si la corrida se cae a mitad,
   lo ya pagado queda guardado.
5. sku_resuelto sale de modelo_interes_mencionado con la misma cascada de
   resolve-models, no del LLM.

Una llamada que falla después de los reintentos no detiene la etapa: se
reporta el lead y queda pendiente para la próxima corrida.
"""

import asyncio
import json
import os
from collections import Counter
from dataclasses import dataclass, field

import psycopg
from openai import APIError, AsyncOpenAI

from backend.db.conexion import conectar
from backend.llm.cache import hash_conversacion
from backend.llm.cliente import ErrorDeExtraccion, cargar_prompt, crear_cliente, extraer
from backend.llm.validacion import campos_informados, violaciones_consistencia
from backend.stages.resolve_models import Catalogo, Moto, resolver_modelo

# v1 se conserva en prompts/ como historial. Ver CLAUDE.md, "Extracción con IA".
PROMPT_VERSION = "extraccion_v5"


@dataclass
class Pendiente:
    lead_id: str
    empresa_id: str
    texto: str
    conversacion_hash: str


@dataclass
class ResultadoExtraccion:
    conteos: Counter = field(default_factory=Counter)
    fallidas: list[tuple[str, str]] = field(default_factory=list)


def textos_por_lead(conn: psycopg.Connection) -> dict[str, tuple[str, str]]:
    """lead_id -> (empresa_id, transcripción). Las fechas se formatean en SQL
    con zona fija para que el texto, y por tanto el hash, no dependa de la
    zona horaria de la sesión."""
    filas = conn.execute(
        """
        SELECT c.lead_id, c.empresa_id, c.conversacion_id,
               to_char(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI'),
               to_char(m.hora, 'HH24:MI'), m.emisor, m.texto
        FROM conversaciones c
        JOIN mensajes m ON m.conversacion_id = c.conversacion_id
        ORDER BY c.lead_id, c.fecha_inicio, c.conversacion_id, m.orden
        """
    ).fetchall()

    lineas: dict[str, list[str]] = {}
    empresas: dict[str, str] = {}
    conversacion_actual: dict[str, str] = {}
    for lead_id, empresa_id, conversacion_id, inicio, hora, emisor, texto in filas:
        if conversacion_actual.get(lead_id) != conversacion_id:
            conversacion_actual[lead_id] = conversacion_id
            lineas.setdefault(lead_id, []).append(f"## Conversación {conversacion_id} · inicio {inicio}")
        lineas[lead_id].append(f"[{hora}] {emisor}: {texto}")
        empresas[lead_id] = empresa_id
    return {lead_id: (empresas[lead_id], "\n".join(texto)) for lead_id, texto in lineas.items()}


def _agregar_derivados(payload: dict, texto: str, catalogo: Catalogo) -> None:
    """Campos que calcula el código, no el LLM. No tocan los campos del LLM."""
    mencionado = payload["modelo_interes_mencionado"]
    resolucion = resolver_modelo(mencionado, catalogo) if mencionado else None
    payload["sku_resuelto"] = resolucion.sku if resolucion else None
    payload["sku_match_method"] = resolucion.metodo if resolucion else None
    payload["campos_informados"] = campos_informados(payload)
    payload["violaciones"] = violaciones_consistencia(payload, texto)


def _recalcular_derivados(
    conn: psycopg.Connection, textos: dict[str, tuple[str, str]], catalogo: Catalogo
) -> None:
    """Los derivados dependen del código (validaciones, catálogo), así que se
    recalculan en cada corrida sobre las extracciones ya guardadas, sin volver
    a llamar a la API. Solo en filas cuyo hash corresponde al texto actual."""
    filas = conn.execute(
        "SELECT lead_id, conversacion_hash, payload FROM extracciones_ia WHERE prompt_version = %s",
        (PROMPT_VERSION,),
    ).fetchall()
    actualizaciones = []
    for lead_id, conversacion_hash, payload in filas:
        if lead_id not in textos:
            continue
        texto = textos[lead_id][1]
        if hash_conversacion(texto, PROMPT_VERSION) != conversacion_hash:
            continue
        _agregar_derivados(payload, texto, catalogo)
        actualizaciones.append((json.dumps(payload, ensure_ascii=False), lead_id, conversacion_hash))
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE extracciones_ia SET payload = %s WHERE lead_id = %s AND conversacion_hash = %s",
            actualizaciones,
        )


def _guardar(
    conn: psycopg.Connection, pendiente: Pendiente, payload: dict, modelo: str, catalogo: Catalogo
) -> None:
    _agregar_derivados(payload, pendiente.texto, catalogo)
    conn.execute(
        """
        INSERT INTO extracciones_ia
            (lead_id, conversacion_hash, empresa_id, prompt_version, modelo_llm, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (lead_id, conversacion_hash) DO NOTHING
        """,
        (
            pendiente.lead_id, pendiente.conversacion_hash, pendiente.empresa_id,
            PROMPT_VERSION, modelo, json.dumps(payload, ensure_ascii=False),
        ),
    )


async def _procesar(
    conn: psycopg.Connection,
    pendientes: list[Pendiente],
    modelo: str,
    concurrencia: int,
    catalogo: Catalogo,
    resultado: ResultadoExtraccion,
) -> None:
    cliente: AsyncOpenAI = crear_cliente()
    semaforo = asyncio.Semaphore(concurrencia)
    prompt = cargar_prompt(PROMPT_VERSION)

    async def una(pendiente: Pendiente) -> tuple[Pendiente, dict | None, str | None]:
        try:
            return pendiente, await extraer(cliente, semaforo, modelo, prompt, pendiente.texto), None
        except (APIError, ErrorDeExtraccion) as error:
            return pendiente, None, f"{type(error).__name__}: {error}"

    for siguiente in asyncio.as_completed([una(p) for p in pendientes]):
        pendiente, payload, error = await siguiente
        if payload is None:
            resultado.conteos["llamadas_fallidas"] += 1
            resultado.fallidas.append((pendiente.lead_id, error or ""))
            continue
        _guardar(conn, pendiente, payload, modelo, catalogo)
        resultado.conteos["extraidas_nuevas"] += 1
    await cliente.close()


async def _repetir(textos: dict[str, str], modelo: str, repeticiones: int, concurrencia: int) -> dict[str, list[dict]]:
    cliente = crear_cliente()
    semaforo = asyncio.Semaphore(concurrencia)
    prompt = cargar_prompt(PROMPT_VERSION)

    async def una(lead_id: str, texto: str) -> tuple[str, dict]:
        return lead_id, await extraer(cliente, semaforo, modelo, prompt, texto)

    resultados = await asyncio.gather(
        *[una(lead_id, texto) for _ in range(repeticiones) for lead_id, texto in textos.items()]
    )
    await cliente.close()

    salidas: dict[str, list[dict]] = {}
    for lead_id, payload in resultados:
        salidas.setdefault(lead_id, []).append(payload)
    return salidas


def medir_variabilidad(lead_ids: list[str], repeticiones: int) -> dict[str, list[dict]]:
    """Envía los mismos leads `repeticiones` veces con el prompt activo, sin
    caché y sin guardar nada. Mide cuánto cambia la salida entre llamadas
    idénticas: una diferencia entre versiones del prompt menor que esa
    variabilidad no se puede atribuir al prompt."""
    modelo = os.getenv("LLM_MODEL", "gpt-4o-mini")
    concurrencia = int(os.getenv("LLM_CONCURRENCIA", "8"))
    with conectar() as conn:
        textos = textos_por_lead(conn)
    seleccion = {lead_id: textos[lead_id][1] for lead_id in lead_ids}
    return asyncio.run(_repetir(seleccion, modelo, repeticiones, concurrencia))


def extraer_conversaciones(limite: int | None = None, lead_ids: list[str] | None = None) -> ResultadoExtraccion:
    """`limite` y `lead_ids` acotan la corrida (muestras de prueba). Sin
    ellos se procesan todos los leads con conversación."""
    modelo = os.getenv("LLM_MODEL", "gpt-4o-mini")
    concurrencia = int(os.getenv("LLM_CONCURRENCIA", "8"))
    resultado = ResultadoExtraccion()

    with conectar() as conn:
        catalogo = Catalogo([Moto(*fila) for fila in conn.execute("SELECT sku, marca, linea FROM motos")])
        ya_extraidas = set(conn.execute("SELECT lead_id, conversacion_hash FROM extracciones_ia").fetchall())
        textos = textos_por_lead(conn)
        resultado.conteos["leads_con_conversacion"] = len(textos)

        pendientes: list[Pendiente] = []
        for lead_id, (empresa_id, texto) in sorted(textos.items()):
            if lead_ids and lead_id not in lead_ids:
                continue
            conversacion_hash = hash_conversacion(texto, PROMPT_VERSION)
            if (lead_id, conversacion_hash) in ya_extraidas:
                resultado.conteos["en_cache"] += 1
                continue
            pendientes.append(Pendiente(lead_id, empresa_id, texto, conversacion_hash))

        if limite is not None:
            pendientes = pendientes[:limite]
        resultado.conteos["enviadas_al_llm"] = len(pendientes)

        asyncio.run(_procesar(conn, pendientes, modelo, concurrencia, catalogo, resultado))
        _recalcular_derivados(conn, textos, catalogo)

        # Violaciones de toda la versión, no solo de esta corrida: con caché,
        # una reejecución no envía nada y aun así debe reportar el estado real.
        violaciones = conn.execute(
            """
            SELECT violacion, count(*)
            FROM extracciones_ia, jsonb_array_elements_text(payload -> 'violaciones') AS violacion
            WHERE prompt_version = %s
            GROUP BY violacion
            """,
            (PROMPT_VERSION,),
        ).fetchall()
        for violacion, cantidad in violaciones:
            resultado.conteos[f"violacion_{violacion}"] = cantidad
    return resultado
