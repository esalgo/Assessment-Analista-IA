"""API contra los datos reales del pipeline, no contra fixtures.

Necesita una base con el pipeline corrido y los usuarios sembrados
(`seed-usuarios`). Se omite salvo PRUEBAS_API_DATOS_REALES=1. En el stack de
Docker, desde la raíz del repo:

    docker compose run --rm -e PRUEBAS_API_DATOS_REALES=1 \\
        -v ./tests:/app/tests:ro -v ./pytest.ini:/app/pytest.ini:ro \\
        api pytest tests/test_api.py

No llama a POST /pipeline/run con un token válido: dispararía el pipeline.
"""

import os

import pytest
from fastapi.testclient import TestClient

from backend.db.conexion import conectar

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_API_DATOS_REALES") != "1", reason="PRUEBAS_API_DATOS_REALES no es 1"
)


@pytest.fixture(scope="module")
def cliente() -> TestClient:
    from backend.api.main import app

    with TestClient(app) as c:
        yield c


def _token(cliente: TestClient, email: str, clave: str) -> dict[str, str]:
    respuesta = cliente.post("/auth/login", json={"email": email, "password": clave})
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def _primer_asesor_con_cola(empresa_id: str) -> str:
    """Consulta de apoyo como superusuario, fuera de la API: solo elige a quién probar."""
    with conectar() as conn:
        return conn.execute(
            """
            SELECT a.asesor_id FROM asesores a JOIN asignaciones g ON g.asesor_id = a.asesor_id
            WHERE a.empresa_id = %s AND a.activo GROUP BY a.asesor_id ORDER BY a.asesor_id LIMIT 1
            """,
            (empresa_id,),
        ).fetchone()[0]


@pytest.fixture(scope="module")
def ids() -> dict[str, str]:
    asesor_01 = _primer_asesor_con_cola("EMP-01")
    asesor_02 = _primer_asesor_con_cola("EMP-02")
    with conectar() as conn:
        otro_01 = conn.execute(
            "SELECT asesor_id FROM asesores WHERE empresa_id = 'EMP-01' AND activo AND asesor_id <> %s LIMIT 1",
            (asesor_01,),
        ).fetchone()[0]
        lead_02 = conn.execute("SELECT lead_id FROM scores WHERE empresa_id = 'EMP-02' LIMIT 1").fetchone()[0]
    return {"asesor_01": asesor_01, "otro_01": otro_01, "asesor_02": asesor_02, "lead_02": lead_02}


@pytest.fixture(scope="module")
def token_asesor_01(cliente: TestClient, ids: dict) -> dict[str, str]:
    return _token(cliente, f"{ids['asesor_01'].lower()}@demo.local", os.environ["SEED_PASSWORD_ASESOR"])


@pytest.fixture(scope="module")
def token_gerente_01(cliente: TestClient) -> dict[str, str]:
    return _token(cliente, "gerente.emp-01@demo.local", os.environ["SEED_PASSWORD_GERENTE"])


def test_health_no_pide_autenticacion(cliente: TestClient) -> None:
    assert cliente.get("/health").json() == {"status": "ok"}


def test_login_con_clave_errada_da_401(cliente: TestClient, ids: dict) -> None:
    respuesta = cliente.post("/auth/login", json={"email": f"{ids['asesor_01'].lower()}@demo.local", "password": "x"})
    assert respuesta.status_code == 401


def test_sin_token_no_hay_cola(cliente: TestClient) -> None:
    assert cliente.get("/leads/hoy").status_code == 401


def test_asesor_ve_su_cola_y_solo_leads_de_su_empresa(cliente: TestClient, ids: dict, token_asesor_01: dict) -> None:
    respuesta = cliente.get("/leads/hoy", headers=token_asesor_01)
    assert respuesta.status_code == 200
    lead_ids = [lead["lead_id"] for lead in respuesta.json()["leads"]]
    with conectar() as conn:
        esperados = conn.execute(
            "SELECT count(*) FROM asignaciones WHERE asesor_id = %s", (ids["asesor_01"],)
        ).fetchone()[0]
        empresas = {e for (e,) in conn.execute("SELECT empresa_id FROM leads WHERE lead_id = ANY(%s)", (lead_ids,))}
    assert len(lead_ids) == esperados > 0
    assert empresas == {"EMP-01"}


def test_asesor_de_otra_empresa_da_403_para_asesor_y_para_gerente(
    cliente: TestClient, ids: dict, token_asesor_01: dict, token_gerente_01: dict
) -> None:
    for token in (token_asesor_01, token_gerente_01):
        respuesta = cliente.get("/leads/hoy", params={"asesor_id": ids["asesor_02"]}, headers=token)
        assert respuesta.status_code == 403


def test_asesor_no_ve_la_cola_de_un_companero_pero_el_gerente_si(
    cliente: TestClient, ids: dict, token_asesor_01: dict, token_gerente_01: dict
) -> None:
    assert cliente.get("/leads/hoy", params={"asesor_id": ids["otro_01"]}, headers=token_asesor_01).status_code == 403
    assert cliente.get("/leads/hoy", params={"asesor_id": ids["otro_01"]}, headers=token_gerente_01).status_code == 200


def test_detalle_de_un_lead_de_otra_empresa_no_existe(cliente: TestClient, ids: dict, token_gerente_01: dict) -> None:
    assert cliente.get(f"/leads/{ids['lead_02']}", headers=token_gerente_01).status_code == 404


def test_detalle_trae_factores_citas_y_skus(cliente: TestClient, token_asesor_01: dict) -> None:
    cola = cliente.get("/leads/hoy", headers=token_asesor_01).json()["leads"]
    detalles = [cliente.get(f"/leads/{lead['lead_id']}", headers=token_asesor_01).json() for lead in cola]
    con_conversacion = [d for d in detalles if any(l["extraccion"] for l in d["leads"])]
    assert con_conversacion, "la cola de prueba no tiene ningún lead con conversación"
    detalle = con_conversacion[0]
    assert detalle["score"]["factores"] is not None
    lead = next(l for l in detalle["leads"] if l["extraccion"])
    assert "justificacion" in lead["extraccion"]
    assert set(lead["sku"]) == {"formulario", "conversacion", "difieren"}


def test_pipeline_sin_token_de_servicio_da_401(cliente: TestClient, token_gerente_01: dict) -> None:
    assert cliente.post("/pipeline/run").status_code == 401
    assert cliente.post("/pipeline/run", headers={"X-Pipeline-Token": "falso"}).status_code == 401
    assert cliente.post("/pipeline/run", headers=token_gerente_01).status_code == 401
