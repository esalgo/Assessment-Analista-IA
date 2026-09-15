"""Acierto por campo de la extracción con LLM contra el set etiquetado a mano.

Uso: python -m backend.llm.validar_extraccion [prompt_version]

Las etiquetas están en docs/set_validacion.md y se escribieron leyendo las
conversaciones, antes de ver la salida del modelo. Este script solo compara:
nunca corrige una etiqueta ni la salida guardada en extracciones_ia.

Un campo etiquetado como `VALOR / comentario` es un caso donde el etiquetador
dudó. Cuenta con el valor escrito antes de la barra y además se reporta aparte:
si el modelo falla justo donde una persona dudó, el campo es ambiguo, no
necesariamente erróneo.
"""

import re
import sys
from dataclasses import dataclass, field

from backend.config import RAIZ
from backend.db.conexion import conectar
from backend.stages.resolve_models import normalizar_texto_modelo

SET_ETIQUETADO = RAIZ / "docs" / "set_validacion.md"
PROMPT_POR_DEFECTO = "extraccion_v5"

# Nombre en el archivo de etiquetas -> nombre en el payload de extracciones_ia.
CAMPOS = {
    "modelo_mencionado": "modelo_interes_mencionado",
    "forma_pago": "forma_pago",
    "manifesto_cuota_inicial": "manifesto_cuota_inicial",
    "cuota_inicial_cop": "cuota_inicial_cop",
    "pidio_cita": "pidio_cita",
    "pidio_cotizacion": "pidio_cotizacion",
    "intencion": "intencion_declarada",
    "objecion": "objecion_principal",
}

ENCABEZADO = re.compile(r"^## (LD-\d+)", re.MULTILINE)
ASIGNACION = re.compile(r"^(\w+)\s*=\s*(.+)$")


@dataclass
class Etiqueta:
    valor: str
    dudoso: bool


@dataclass
class Campo:
    aciertos: int = 0
    total: int = 0
    dudosos_fallados: int = 0
    fallos: list[tuple[str, str, str, bool]] = field(default_factory=list)


def leer_etiquetas(ruta) -> dict[str, dict[str, Etiqueta]]:
    """{lead_id: {campo: Etiqueta}} a partir de los bloques ``` del archivo."""
    texto = ruta.read_text(encoding="utf-8")
    partes = ENCABEZADO.split(texto)[1:]  # [lead_id, cuerpo, lead_id, cuerpo, ...]
    etiquetas = {}
    for lead_id, cuerpo in zip(partes[::2], partes[1::2]):
        bloque = cuerpo.split("```")[1]
        campos = {}
        for linea in bloque.splitlines():
            coincidencia = ASIGNACION.match(linea.strip())
            if coincidencia and coincidencia[1] in CAMPOS:
                valor, _, comentario = coincidencia[2].partition("/")
                campos[coincidencia[1]] = Etiqueta(valor.strip(), bool(comentario.strip()))
        etiquetas[lead_id] = campos
    return etiquetas


def iguales(campo: str, etiqueta: str, extraido) -> bool:
    """El modelo del texto se compara normalizado (minúsculas, sin tildes);
    el resto de campos son enumeraciones o un entero, y se comparan exactos."""
    if campo == "modelo_mencionado":
        return normalizar_texto_modelo(etiqueta) == normalizar_texto_modelo(extraido or "")
    if campo == "cuota_inicial_cop":
        return (None if etiqueta.lower() == "null" else int(etiqueta)) == extraido
    return etiqueta == extraido


def medir(prompt_version: str) -> None:
    etiquetas = leer_etiquetas(SET_ETIQUETADO)
    with conectar() as conn:
        payloads = dict(
            conn.execute(
                "SELECT lead_id, payload FROM extracciones_ia WHERE prompt_version = %s AND lead_id = ANY(%s)",
                (prompt_version, list(etiquetas)),
            ).fetchall()
        )

    faltantes = sorted(set(etiquetas) - set(payloads))
    if faltantes:
        print(f"Sin extracción con {prompt_version}: {', '.join(faltantes)}\n")

    resultados = {campo: Campo() for campo in CAMPOS}
    for lead_id, campos in etiquetas.items():
        payload = payloads.get(lead_id)
        if payload is None:
            continue
        for campo, etiqueta in campos.items():
            extraido = payload[CAMPOS[campo]]
            resultado = resultados[campo]
            resultado.total += 1
            if iguales(campo, etiqueta.valor, extraido):
                resultado.aciertos += 1
            else:
                resultado.fallos.append((lead_id, etiqueta.valor, str(extraido), etiqueta.dudoso))
                resultado.dudosos_fallados += etiqueta.dudoso

    print(f"Acierto por campo — {prompt_version}, {len(payloads)} conversaciones etiquetadas\n")
    print(f"{'Campo':<24} {'Acierto':>10}  {'%':>6}  {'De ellos, dudosos':>18}")
    for campo, r in resultados.items():
        porcentaje = 100 * r.aciertos / r.total if r.total else 0
        print(f"{campo:<24} {r.aciertos:>4} / {r.total:<3} {porcentaje:>6.0f}  {r.dudosos_fallados:>18}")

    aciertos = sum(r.aciertos for r in resultados.values())
    total = sum(r.total for r in resultados.values())
    print(f"\n{'total':<24} {aciertos:>4} / {total:<3} {100 * aciertos / total:>6.0f}")

    print("\nDiscrepancias (etiqueta -> extracción):")
    for campo, r in resultados.items():
        for lead_id, etiqueta, extraido, dudoso in r.fallos:
            print(f"  {lead_id}  {campo:<24} {etiqueta!r} -> {extraido!r}{'   (etiqueta dudosa)' if dudoso else ''}")


if __name__ == "__main__":
    medir(sys.argv[1] if len(sys.argv) > 1 else PROMPT_POR_DEFECTO)
