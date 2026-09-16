"""Endpoints de la API.

Regla base: empresa_id nunca es parámetro. Sale del token (usuario_actual) y
se aplica en el motor con RLS (sesion_tenant). Un lead o un asesor de otra
empresa no se ve: para la consulta simplemente no existe.
"""

import secrets
import threading

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel

from backend.api.auth import Usuario, clave_correcta, crear_token, usuario_actual
from backend.api.db import pool, sesion_tenant
from backend.config import pipeline_token

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Login ---------------------------------------------------------------------


class Credenciales(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(credenciales: Credenciales) -> dict[str, str]:
    """No baja a app_tenant: todavía no se sabe la empresa, y usuarios no
    tiene RLS por eso mismo. Solo lee la fila del email pedido."""
    with pool().connection() as conn:
        fila = conn.execute(
            """
            SELECT usuario_id::text, empresa_id, asesor_id, rol, password_hash
            FROM usuarios WHERE email = %s AND activo
            """,
            (credenciales.email.strip().lower(),),
        ).fetchone()
    if not clave_correcta(credenciales.password, fila[4] if fila else None):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "email o contraseña incorrectos")
    usuario = Usuario(usuario_id=fila[0], empresa_id=fila[1], asesor_id=fila[2], rol=fila[3])
    return {"access_token": crear_token(usuario), "token_type": "bearer"}


# --- Vistas del gerente ----------------------------------------------------------


def exigir_gerente(usuario: Usuario) -> None:
    if usuario.rol != "gerente":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "solo un gerente tiene acceso")


@router.get("/asesores")
def asesores(
    usuario: Usuario = Depends(usuario_actual),
    conn: psycopg.Connection = Depends(sesion_tenant),
) -> list[dict]:
    """Los asesores activos para el selector del gerente. La consulta no filtra
    por empresa: lo hace RLS, así que un gerente nunca ve asesores de otra."""
    exigir_gerente(usuario)
    filas = conn.execute(
        "SELECT asesor_id, nombre, punto_venta_id FROM asesores WHERE activo ORDER BY punto_venta_id, asesor_id"
    ).fetchall()
    return [{"asesor_id": a, "nombre": n, "punto_venta_id": pv} for a, n, pv in filas]


@router.get("/resumen")
def resumen(
    usuario: Usuario = Depends(usuario_actual),
    conn: psycopg.Connection = Depends(sesion_tenant),
) -> list[dict]:
    """Días de cartera por punto de venta: cuántos días tardan los asesores
    activos en atender a todos los clientes activos (primer contacto +
    seguimiento). Misma fórmula que el resumen de la etapa assign.
    Ordenado de mayor a menor: arriba el punto de venta más represado."""
    exigir_gerente(usuario)
    asesores_pv = {
        pv: (activos, inactivos, cap)
        for pv, activos, inactivos, cap in conn.execute(
            """
            SELECT punto_venta_id,
                   count(*) FILTER (WHERE activo),
                   count(*) FILTER (WHERE NOT activo),
                   coalesce(sum(capacidad_diaria_leads) FILTER (WHERE activo), 0)
            FROM asesores GROUP BY punto_venta_id
            """
        )
    }
    clientes_pv = {
        pv: (pendientes, seguimiento)
        for pv, pendientes, seguimiento in conn.execute(
            """
            SELECT punto_venta_id,
                   count(*) FILTER (WHERE cola = 'primer_contacto'),
                   count(*) FILTER (WHERE cola = 'seguimiento')
            FROM scores GROUP BY punto_venta_id
            """
        )
    }

    filas = []
    for pv in sorted(asesores_pv.keys() | clientes_pv.keys()):
        activos, inactivos, cap = asesores_pv.get(pv, (0, 0, 0))
        pendientes, seguimiento = clientes_pv.get(pv, (0, 0))
        cartera = pendientes + seguimiento
        filas.append({
            "punto_venta_id": pv,
            "asesores_activos": activos,
            "asesores_inactivos": inactivos,
            "capacidad_diaria": cap,
            "pendientes": pendientes,
            "seguimiento": seguimiento,
            "clientes_activos": cartera,
            # None cuando no hay capacidad: la cartera no se atiende nunca.
            "dias_de_cartera": round(cartera / cap, 1) if cap else None,
        })
    # Sin capacidad (None) va primero: es el peor caso, no el mejor.
    return sorted(filas, key=lambda f: (f["dias_de_cartera"] is None, f["dias_de_cartera"] or 0), reverse=True)


# --- Cola del día ------------------------------------------------------------


@router.get("/leads/hoy")
def leads_hoy(
    asesor_id: str | None = None,
    usuario: Usuario = Depends(usuario_actual),
    conn: psycopg.Connection = Depends(sesion_tenant),
) -> dict:
    """La lista de gestión del día de un asesor: primero primer contacto,
    después seguimiento, cada una en el orden de la asignación.

    - Un asesor solo ve su propia cola (asesor_id opcional).
    - Un gerente ve la de cualquier asesor de su empresa (asesor_id obligatorio).
    - Un asesor_id de otra empresa responde 403: con RLS no aparece.
    """
    if usuario.rol == "asesor":
        asesor_id = asesor_id or usuario.asesor_id
        if asesor_id != usuario.asesor_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "un asesor solo puede ver su propia cola")
    elif asesor_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "asesor_id es obligatorio para un gerente")

    asesor = conn.execute(
        "SELECT asesor_id, nombre, punto_venta_id FROM asesores WHERE asesor_id = %s", (asesor_id,)
    ).fetchone()
    if asesor is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "el asesor no pertenece a tu empresa")

    fecha = conn.execute("SELECT max(fecha) FROM asignaciones").fetchone()[0]
    filas = conn.execute(
        """
        SELECT g.cola, g.orden, s.lead_id, l.nombre_cliente, l.telefono_normalizado, l.canal,
               s.score, s.temperatura, s.estado_consolidado, s.horas_desempate, s.sin_senal_conversacional
        FROM asignaciones g
        JOIN scores s ON s.lead_id = g.lead_id
        JOIN leads l ON l.lead_id = g.lead_id
        WHERE g.asesor_id = %s AND g.fecha = %s
        ORDER BY g.cola <> 'primer_contacto', g.orden
        """,
        (asesor_id, fecha),
    ).fetchall()
    columnas = [
        "cola", "orden", "lead_id", "nombre_cliente", "telefono", "canal", "score", "temperatura",
        "estado", "horas_transcurridas", "sin_senal_conversacional",
    ]
    return {
        "fecha": fecha,
        "asesor": {"asesor_id": asesor[0], "nombre": asesor[1], "punto_venta_id": asesor[2]},
        "leads": [dict(zip(columnas, fila)) for fila in filas],
    }


# --- Detalle de un lead -------------------------------------------------------


@router.get("/leads/{lead_id}")
def detalle_lead(
    lead_id: str,
    usuario: Usuario = Depends(usuario_actual),
    conn: psycopg.Connection = Depends(sesion_tenant),
) -> dict:
    """El cliente completo: su score con los factores, las citas textuales de
    la extracción y los dos SKU (formulario y conversación) cuando difieren.

    - Si lead_id es un lead absorbido por dedupe, se responde con su cliente
      (el grupo del canónico).
    - Un lead de otra empresa responde 404: con RLS no existe.
    - Un asesor solo ve los clientes de su cola del día, la misma fecha que
      /leads/hoy; uno de otro asesor de su empresa responde 403. Un gerente
      ve cualquiera de su empresa."""
    fila = conn.execute(
        "SELECT coalesce(lead_canonico_id, lead_id) FROM leads WHERE lead_id = %s", (lead_id,)
    ).fetchone()
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead no encontrado")
    cliente_id = fila[0]

    if usuario.rol == "asesor":
        en_su_cola = conn.execute(
            """
            SELECT 1 FROM asignaciones
            WHERE lead_id = %s AND asesor_id = %s
              AND fecha = (SELECT max(fecha) FROM asignaciones)
            """,
            (cliente_id, usuario.asesor_id),
        ).fetchone()
        if en_su_cola is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "un asesor solo puede ver los clientes de su cola")

    leads = conn.execute(
        """
        SELECT l.lead_id, l.nombre_cliente, l.telefono_normalizado, l.email, l.canal, l.punto_venta_id,
               l.fecha_registro, l.estado_gestion, l.modelo_interes_texto, l.sku,
               m.marca || ' ' || m.linea, e.payload
        FROM leads l
        LEFT JOIN motos m ON m.sku = l.sku
        LEFT JOIN extracciones_ia e ON e.lead_id = l.lead_id AND e.prompt_version = 'extraccion_v5'
        WHERE coalesce(l.lead_canonico_id, l.lead_id) = %s
        ORDER BY l.fecha_registro
        """,
        (cliente_id,),
    ).fetchall()
    nombres_moto = dict(conn.execute("SELECT sku, marca || ' ' || linea FROM motos").fetchall())

    score = conn.execute(
        """
        SELECT score, temperatura, cola, estado_consolidado, punto_venta_id, horas_desempate,
               sin_senal_conversacional, factores, score_version
        FROM scores WHERE lead_id = %s
        """,
        (cliente_id,),
    ).fetchone()
    asignacion = conn.execute(
        """
        SELECT fecha, asesor_id, cola, orden FROM asignaciones
        WHERE lead_id = %s ORDER BY fecha DESC LIMIT 1
        """,
        (cliente_id,),
    ).fetchone()

    detalle_leads = []
    for (lid, nombre, telefono, email, canal, pv, registro, estado, modelo_texto, sku_form,
         nombre_form, payload) in leads:
        sku_conv = payload["sku_resuelto"] if payload else None
        detalle_leads.append({
            "lead_id": lid,
            "canal": canal,
            "punto_venta_id": pv,
            "fecha_registro": registro,
            "estado_gestion": estado,
            "sku": {
                "formulario": {"texto": modelo_texto, "sku": sku_form, "modelo": nombre_form},
                "conversacion": {
                    "texto": payload["modelo_interes_mencionado"] if payload else None,
                    "sku": sku_conv,
                    "modelo": nombres_moto.get(sku_conv),
                },
                "difieren": bool(sku_form and sku_conv and sku_form != sku_conv),
            },
            "extraccion": None if payload is None else {
                "justificacion": payload["justificacion"],
                "pidio_cita": payload["pidio_cita"],
                "manifesto_cuota_inicial": payload["manifesto_cuota_inicial"],
                "cuota_inicial_cop": payload["cuota_inicial_cop"],
                "forma_pago": payload["forma_pago"],
                "pidio_cotizacion": payload["pidio_cotizacion"],
                "intencion_declarada": payload["intencion_declarada"],
                "objecion_principal": payload["objecion_principal"],
                "violaciones": payload["violaciones"],
            },
        })

    canonico = leads[0]
    return {
        "cliente_id": cliente_id,
        "nombre_cliente": canonico[1],
        "telefono": canonico[2],
        "email": canonico[3],
        "score": None if score is None else {
            "score": score[0], "temperatura": score[1], "cola": score[2], "estado": score[3],
            "punto_venta_id": score[4], "horas_transcurridas": score[5],
            "sin_senal_conversacional": score[6], "factores": score[7], "score_version": score[8],
        },
        "asignacion": None if asignacion is None else {
            "fecha": asignacion[0], "asesor_id": asignacion[1], "cola": asignacion[2], "orden": asignacion[3],
        },
        "leads": detalle_leads,
    }


# --- Pipeline -------------------------------------------------------------------

_pipeline_en_curso = threading.Lock()


def _correr_pipeline() -> None:
    # Import local: el CLI importa todas las etapas y no hace falta al arrancar la API.
    from backend.cli import run_all

    try:
        run_all()
    finally:
        _pipeline_en_curso.release()


@router.post("/pipeline/run", status_code=status.HTTP_202_ACCEPTED)
def pipeline_run(background: BackgroundTasks, x_pipeline_token: str | None = Header(default=None)) -> dict[str, str]:
    """Lo dispara n8n. No usa JWT sino un token de servicio en X-Pipeline-Token.
    El pipeline corre como superusuario (procesa las tres empresas) y en
    segundo plano: la respuesta llega enseguida y el log sale en `docker compose logs api`."""
    if x_pipeline_token is None or not secrets.compare_digest(x_pipeline_token, pipeline_token()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Pipeline-Token ausente o inválido")
    if not _pipeline_en_curso.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "ya hay una corrida del pipeline en curso")
    background.add_task(_correr_pipeline)
    return {"estado": "iniciado"}
