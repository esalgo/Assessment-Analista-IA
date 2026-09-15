"""Etapa dedupe: identidad por (empresa_id, telefono_normalizado) con guarda de nombre."""

from datetime import datetime
from itertools import permutations

import pytest

from backend.config import RAIZ
from backend.db.conexion import conectar
from backend.stages.dedupe import (
    LeadDedupe,
    agrupar_por_identidad,
    comparar_nombres,
    deduplicar,
    elegir_canonico,
    nombre_mas_completo,
    nombres_compatibles,
    planificar_grupo,
)
from backend.stages.ingest import ingestar
from backend.stages.load_reference import cargar_referencia
from backend.stages.normalize import ZONA, normalizar
from backend.stages.resolve_models import resolver_modelos


def _lead(lead_id: str, empresa: str = "EMP-01", canal: str = "WhatsApp", nombre: str = "Yuliana Castaño Valencia",
          fecha: str = "2026-08-10 10:00", ambigua: bool = False, telefono: str = "3002859667") -> LeadDedupe:
    return LeadDedupe(lead_id, empresa, telefono, canal, nombre, None,
                      datetime.fromisoformat(fecha).replace(tzinfo=ZONA), ambigua)


# --- Guarda de nombre ------------------------------------------------------

def test_solo_tildes_o_mayusculas_son_iguales() -> None:
    assert comparar_nombres("Estefanía Pérez Ramírez", "ESTEFANIA PEREZ RAMIREZ") == "iguales"


def test_falta_un_dato_es_compatible() -> None:
    assert comparar_nombres("Yuliana Castaño Valencia", "Y. Castaño Valencia") == "falta_dato"
    assert comparar_nombres("Duván Arias Mosquera", "Duván Arias") == "falta_dato"
    assert comparar_nombres("Angie Paola Agudelo Ospina", "A. Agudelo Ospina") == "falta_dato"
    assert comparar_nombres("María Valencia", "María Fernanda Valencia Salazar") == "falta_dato"


def test_datos_que_se_contradicen_no_son_compatibles() -> None:
    # Ambos traen dos apellidos y solo coincide uno
    assert comparar_nombres("M. Muñoz Ramírez", "Marcela Muñoz Escobar") == "contradicen"
    assert comparar_nombres("Yuliana Castaño Valencia", "Carlos Castaño Valencia") == "contradicen"
    assert comparar_nombres("Duván Arias", "Duván Gómez Mosquera") == "contradicen"
    assert not nombres_compatibles("M. Muñoz Ramírez", "Marcela Muñoz Escobar")


def test_primer_nombre_completo_distinto_se_contradice() -> None:
    # Misma inicial y mismos apellidos, pero dos nombres completos distintos
    assert comparar_nombres("Marcela Muñoz Escobar", "María Muñoz Escobar") == "contradicen"
    # Si uno está abreviado, la inicial no contradice: es falta de dato
    assert comparar_nombres("M. Muñoz Escobar", "María Muñoz Escobar") == "falta_dato"


def test_segundo_nombre_distinto_se_contradice() -> None:
    # Ambos traen segundo nombre y no coincide
    assert comparar_nombres("Juan Carlos Pérez Gómez", "Juan David Pérez Gómez") == "contradicen"
    # Solo uno trae segundo nombre: falta de dato
    assert comparar_nombres("Juan Pérez Gómez", "Juan Carlos Pérez Gómez") == "falta_dato"


# --- Canónico y nombre del cliente -----------------------------------------

def test_canonico_es_el_de_registro_mas_antiguo_no_el_lead_id_menor() -> None:
    antiguo = _lead("LD-01410", fecha="2026-08-26 09:00")
    reciente = _lead("LD-00115", fecha="2026-09-04 09:00")
    assert elegir_canonico([reciente, antiguo]) is antiguo


def test_canonico_con_misma_fecha_desempata_por_lead_id() -> None:
    a, b = _lead("LD-00200"), _lead("LD-00100")
    assert elegir_canonico([a, b]) is b


def test_nombre_mas_completo_sigue_el_orden_explicito() -> None:
    canonico = _lead("LD-1", nombre="Y. Castaño Valencia")
    assert nombre_mas_completo([canonico, _lead("LD-2", nombre="Yuliana Castaño Valencia")], canonico) == "Yuliana Castaño Valencia"

    canonico = _lead("LD-1", nombre="Duván Arias")
    assert nombre_mas_completo([canonico, _lead("LD-2", nombre="Duván Arias Mosquera")], canonico) == "Duván Arias Mosquera"

    canonico = _lead("LD-1", nombre="Estefania Perez Ramirez")
    assert nombre_mas_completo([canonico, _lead("LD-2", nombre="Estefanía Pérez Ramírez")], canonico) == "Estefanía Pérez Ramírez"

    canonico = _lead("LD-2", nombre="Natalia Zapata Marín")
    assert nombre_mas_completo([_lead("LD-1", nombre="Natalia Zapata Marin"), canonico], canonico) == "Natalia Zapata Marín"


def test_nombre_mas_completo_no_depende_del_orden_de_entrada() -> None:
    leads = [_lead("LD-3", nombre="Ana Ruiz Gil"), _lead("LD-1", nombre="Ana Ruiz Gil"), _lead("LD-2", nombre="Ana Ruíz Gil")]
    canonico = leads[1]
    assert {nombre_mas_completo(list(orden), canonico) for orden in permutations(leads)} == {"Ana Ruíz Gil"}


# --- Plan del grupo --------------------------------------------------------

def test_duplicado_cross_canal_se_fusiona_con_motivo() -> None:
    plan = planificar_grupo([
        _lead("LD-00052", canal="Formulario Web", nombre="Y. Castaño Valencia", fecha="2026-08-06 10:00"),
        _lead("LD-00004", canal="Meta Ads", fecha="2026-08-03 10:00"),
    ])
    assert plan.canonico.lead_id == "LD-00004"
    assert plan.canales == ["Formulario Web", "Meta Ads"]
    assert plan.fusiones[0].motivo == {
        "regla": "mismo_telefono_empresa", "confianza": 1.0, "cruza_canal": True,
        "nombre_compatible": True, "comparacion_nombre": "falta_dato", "fecha_ambigua": False,
    }


def test_fecha_ambigua_en_el_grupo_baja_la_confianza() -> None:
    plan = planificar_grupo([_lead("LD-1"), _lead("LD-2", fecha="2026-08-12 10:00", ambigua=True)])
    assert plan.fusiones[0].motivo["confianza"] == 0.8


def test_telefono_compartido_con_nombre_incompatible_no_se_fusiona() -> None:
    plan = planificar_grupo([_lead("LD-1"), _lead("LD-2", nombre="Carlos Gómez Arias", fecha="2026-08-12 10:00")])
    assert plan.fusiones == []
    assert [l.lead_id for l in plan.no_fusionados] == ["LD-2"]


def test_duplicado_cross_empresa_no_se_fusiona() -> None:
    grupos = agrupar_por_identidad([_lead("LD-1", empresa="EMP-02"), _lead("LD-2", empresa="EMP-03")])
    assert len(grupos) == 2
    assert all(planificar_grupo(g).fusiones == [] for g in grupos.values())


# --- Etapa completa --------------------------------------------------------

@pytest.fixture
def deduplicado(base_de_prueba: None) -> dict:
    ingestar(RAIZ / "data" / "input")
    cargar_referencia()
    normalizar()
    resolver_modelos()
    return deduplicar()


def test_perfil_sobre_los_datos_reales(deduplicado: dict) -> None:
    assert deduplicado["grupos_con_duplicados"] == 49
    assert deduplicado["fusion_cruza_canal"] == 28
    assert deduplicado["fusion_mismo_canal"] == 21
    assert deduplicado["telefonos_en_varias_empresas_no_fusionados"] == 91
    assert deduplicado["telefono_compartido_nombre_incompatible"] == 0
    assert deduplicado["leads_canonicos"] == deduplicado["clientes"] == 1451
    with conectar() as conn:
        comparaciones = dict(conn.execute(
            """
            SELECT motivo_fusion->>'comparacion_nombre', count(*) FROM leads
            WHERE lead_canonico_id IS NOT NULL GROUP BY 1
            """
        ).fetchall())
    assert comparaciones == {"iguales": 31, "falta_dato": 18}


def test_mismo_telefono_en_dos_empresas_son_dos_clientes(deduplicado: dict) -> None:
    with conectar() as conn:
        fila = conn.execute(
            """
            SELECT count(DISTINCT cliente_id), count(*) FILTER (WHERE lead_canonico_id IS NOT NULL)
            FROM leads WHERE telefono_normalizado = '3001068650'
            """
        ).fetchone()
    assert fila == (2, 0)


def test_reejecutar_da_el_mismo_md5_con_cliente_id_estables(deduplicado: dict) -> None:
    consulta = """
        SELECT (SELECT md5(string_agg(concat_ws('|', lead_id, cliente_id, lead_canonico_id, motivo_fusion, canales),
                                      ',' ORDER BY lead_id)) FROM leads),
               (SELECT md5(string_agg(concat_ws('|', cliente_id, empresa_id, telefono_normalizado, nombre, email),
                                      ',' ORDER BY cliente_id)) FROM clientes)
    """
    with conectar() as conn:
        antes = conn.execute(consulta).fetchone()
    assert deduplicar() == deduplicado
    with conectar() as conn:
        assert conn.execute(consulta).fetchone() == antes
