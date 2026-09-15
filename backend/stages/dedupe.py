"""Etapa dedupe: identidad de cliente dentro de cada empresa.

Clave de identidad: (empresa_id, telefono_normalizado). Un mismo teléfono en
dos empresas son dos clientes distintos y nunca se fusionan (requisito 8).

Dentro de un grupo de la misma empresa:
- Canónico: el lead con fecha_registro más antigua; desempate por lead_id.
- Se fusiona con el canónico cada lead cuyo nombre no lo contradice (ver
  `comparar_nombres`): falta de datos sí, datos opuestos no. El absorbido queda en leads con
  lead_canonico_id y motivo_fusion; el canónico acumula los canales.
- El canónico conserva sus propios datos (punto de venta, estado, SKU).
  Consolidar el estado del grupo le corresponde a score.

La etapa recalcula todo desde cero en cada corrida, en una transacción.
Los cliente_id se mantienen estables porque clientes se actualiza con upsert.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from backend.catalogos import clave
from backend.db.conexion import conectar

REGLA = "mismo_telefono_empresa"
CONFIANZA_BASE = 1.0
# Si alguna fecha de registro del grupo fue elegida por heurística, también
# lo fue la elección del canónico.
CONFIANZA_FECHA_AMBIGUA = 0.8


@dataclass
class LeadDedupe:
    lead_id: str
    empresa_id: str
    telefono: str
    canal: str
    nombre: str
    email: str | None
    fecha_registro: datetime
    fecha_registro_ambigua: bool


@dataclass
class Fusion:
    absorbido: LeadDedupe
    motivo: dict


@dataclass
class PlanGrupo:
    canonico: LeadDedupe
    fusiones: list[Fusion]
    no_fusionados: list[LeadDedupe]  # mismo teléfono, nombre incompatible

    @property
    def canales(self) -> list[str]:
        return sorted({self.canonico.canal, *(f.absorbido.canal for f in self.fusiones)})


# --- Funciones puras -------------------------------------------------------

def _palabras_nombre(nombre: str) -> list[str]:
    return clave(nombre).replace(".", "").split()


def _apellidos(palabras: list[str]) -> list[str]:
    """Las dos últimas palabras si hay tres o más; la última si hay dos.
    Verificado sobre los 1.500 leads: 4 palabras = 2 nombres + 2 apellidos,
    3 = 1 + 2, 2 = 1 + 1. Ningún nombre de 3 palabras trae nombre compuesto."""
    return palabras[-2:] if len(palabras) >= 3 else palabras[-1:]


def comparar_nombres(a: str, b: str) -> str:
    """Clasifica dos nombres del mismo teléfono y empresa:

    'iguales'      idénticos tras normalizar tildes, mayúsculas y espacios
    'falta_dato'   uno trae menos información pero nada se contradice:
                   nombre abreviado a su inicial, o un solo apellido que
                   coincide con uno de los dos del otro
    'contradicen'  en primer o segundo nombre, cuando ambos lo traen: distinta
                   inicial, o ambos completos y distintos ('Marcela' contra
                   'María', 'Juan Carlos' contra 'Juan David'); o ambos traen
                   dos apellidos y no son los mismos ('M. Muñoz Ramírez'
                   contra 'Marcela Muñoz Escobar')
    """
    pa, pb = _palabras_nombre(a), _palabras_nombre(b)
    if len(pa) < 2 or len(pb) < 2:
        return "contradicen"
    if pa == pb:
        return "iguales"
    apellidos_a, apellidos_b = _apellidos(pa), _apellidos(pb)
    nombres_a, nombres_b = pa[: -len(apellidos_a)], pb[: -len(apellidos_b)]
    # Primer y segundo nombre, cuando ambos lo traen. zip se detiene en el más
    # corto: si solo uno trae segundo nombre, es falta de dato.
    for nombre_a, nombre_b in zip(nombres_a, nombres_b):
        if nombre_a[0] != nombre_b[0]:
            return "contradicen"
        # Tras quitar el punto, un nombre abreviado queda de una letra.
        ambos_completos = len(nombre_a) > 1 and len(nombre_b) > 1
        if ambos_completos and nombre_a != nombre_b:
            return "contradicen"
    if len(apellidos_a) == 2 and len(apellidos_b) == 2:
        return "falta_dato" if apellidos_a == apellidos_b else "contradicen"
    corto, largo = sorted((apellidos_a, apellidos_b), key=len)
    return "falta_dato" if corto[0] in largo else "contradicen"


def nombres_compatibles(a: str, b: str) -> bool:
    return comparar_nombres(a, b) != "contradicen"


def elegir_canonico(leads: list[LeadDedupe]) -> LeadDedupe:
    return min(leads, key=lambda lead: (lead.fecha_registro, lead.lead_id))


ABREVIATURA = re.compile(r"^\w\.$")


def nombre_mas_completo(leads: list[LeadDedupe], canonico: LeadDedupe) -> str:
    """Nombre para el cliente. Orden explícito, cada criterio solo desempata el anterior:
    1. sin palabras abreviadas con inicial y punto ('Y.')
    2. más palabras
    3. conserva tildes ('Estefanía' antes que 'Estefania')
    4. el del canónico
    5. lead_id menor (garantiza un único ganador aunque todo lo demás empate)
    """
    def orden(lead: LeadDedupe) -> tuple[bool, int, bool, bool, str]:
        palabras = lead.nombre.split()
        sin_abreviar = not any(ABREVIATURA.match(p) for p in palabras)
        con_tildes = clave(lead.nombre) != " ".join(lead.nombre.lower().split())
        return (not sin_abreviar, -len(palabras), not con_tildes, lead is not canonico, lead.lead_id)
    return min(leads, key=orden).nombre


def planificar_grupo(leads: list[LeadDedupe]) -> PlanGrupo:
    """`leads` comparten empresa_id y telefono."""
    canonico = elegir_canonico(leads)
    compatibles = [l for l in leads if l is not canonico and nombres_compatibles(l.nombre, canonico.nombre)]
    no_fusionados = [l for l in leads if l is not canonico and l not in compatibles]

    fecha_ambigua = canonico.fecha_registro_ambigua or any(l.fecha_registro_ambigua for l in compatibles)
    fusiones = [
        Fusion(
            absorbido=lead,
            motivo={
                "regla": REGLA,
                "confianza": CONFIANZA_FECHA_AMBIGUA if fecha_ambigua else CONFIANZA_BASE,
                "cruza_canal": lead.canal != canonico.canal,
                "nombre_compatible": True,
                "comparacion_nombre": comparar_nombres(lead.nombre, canonico.nombre),
                "fecha_ambigua": fecha_ambigua,
            },
        )
        for lead in compatibles
    ]
    return PlanGrupo(canonico, fusiones, no_fusionados)


def agrupar_por_identidad(leads: list[LeadDedupe]) -> dict[tuple[str, str], list[LeadDedupe]]:
    grupos: dict[tuple[str, str], list[LeadDedupe]] = {}
    for lead in leads:
        grupos.setdefault((lead.empresa_id, lead.telefono), []).append(lead)
    return grupos


# --- Base de datos ---------------------------------------------------------

def _upsert_cliente(conn: psycopg.Connection, empresa_id: str, telefono: str, nombre: str, email: str | None) -> int:
    fila = conn.execute(
        """
        INSERT INTO clientes (empresa_id, telefono_normalizado, nombre, email)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (empresa_id, telefono_normalizado) DO UPDATE SET
            nombre = EXCLUDED.nombre,
            email = EXCLUDED.email
        RETURNING cliente_id
        """,
        (empresa_id, telefono, nombre, email),
    ).fetchone()
    assert fila is not None
    return fila[0]


def deduplicar() -> Counter:
    resumen: Counter = Counter()
    with conectar() as conn, conn.transaction():
        # Punto de partida limpio: lo que dedupe escribió la vez anterior se recalcula.
        conn.execute(
            """
            UPDATE leads SET cliente_id = NULL, lead_canonico_id = NULL,
                             motivo_fusion = NULL, canales = ARRAY[canal]
            """
        )

        leads = [
            LeadDedupe(*fila)
            for fila in conn.execute(
                """
                SELECT lead_id, empresa_id, telefono_normalizado, canal, nombre_cliente,
                       email, fecha_registro, fecha_registro_ambigua
                FROM leads WHERE telefono_valido
                ORDER BY lead_id
                """
            )
        ]
        resumen["leads_con_telefono_valido"] = len(leads)

        for (empresa_id, telefono), grupo in agrupar_por_identidad(leads).items():
            plan = planificar_grupo(grupo)
            fusionados = [plan.canonico, *(f.absorbido for f in plan.fusiones)]
            email = plan.canonico.email or next((l.email for l in fusionados if l.email), None)
            cliente_id = _upsert_cliente(
                conn, empresa_id, telefono, nombre_mas_completo(fusionados, plan.canonico), email
            )

            conn.execute(
                "UPDATE leads SET cliente_id = %s WHERE empresa_id = %s AND telefono_normalizado = %s",
                (cliente_id, empresa_id, telefono),
            )
            conn.execute("UPDATE leads SET canales = %s WHERE lead_id = %s", (plan.canales, plan.canonico.lead_id))
            for fusion in plan.fusiones:
                conn.execute(
                    "UPDATE leads SET lead_canonico_id = %s, motivo_fusion = %s WHERE lead_id = %s",
                    (plan.canonico.lead_id, Jsonb(fusion.motivo), fusion.absorbido.lead_id),
                )
                resumen["leads_absorbidos"] += 1
                resumen["fusion_cruza_canal" if fusion.motivo["cruza_canal"] else "fusion_mismo_canal"] += 1
                if fusion.motivo["fecha_ambigua"]:
                    resumen["fusion_con_fecha_ambigua"] += 1
            if len(grupo) > 1:
                resumen["grupos_con_duplicados"] += 1
            resumen["telefono_compartido_nombre_incompatible"] += len(plan.no_fusionados)

        conn.execute("DELETE FROM clientes WHERE cliente_id NOT IN (SELECT cliente_id FROM leads WHERE cliente_id IS NOT NULL)")

        for nombre, consulta in {
            "clientes": "SELECT count(*) FROM clientes",
            "leads_canonicos": "SELECT count(*) FROM leads WHERE lead_canonico_id IS NULL",
            "telefonos_en_varias_empresas_no_fusionados": """
                SELECT count(*) FROM (SELECT telefono_normalizado FROM leads WHERE telefono_valido
                GROUP BY 1 HAVING count(DISTINCT empresa_id) > 1) t""",
        }.items():
            fila = conn.execute(consulta).fetchone()
            assert fila is not None
            resumen[nombre] = fila[0]
    return resumen
