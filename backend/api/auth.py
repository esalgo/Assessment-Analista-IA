"""Contraseñas, tokens JWT y el usuario del request."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config import jwt_secret

ALGORITMO = "HS256"
DURACION_TOKEN = timedelta(hours=8)
_bearer = HTTPBearer(auto_error=False)

# Hash de referencia para comparar cuando el email no existe: así el login
# tarda lo mismo con un email inexistente que con una contraseña errada.
_HASH_FICTICIO = bcrypt.hashpw(b"no-es-una-clave", bcrypt.gensalt())


@dataclass
class Usuario:
    usuario_id: str
    empresa_id: str
    asesor_id: str | None
    rol: str


def hashear(clave: str) -> str:
    return bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def clave_correcta(clave: str, hash_guardado: str | None) -> bool:
    """hash_guardado es None cuando el email no existe. Igual se hace una
    comparación bcrypt, para no revelar por el tiempo de respuesta qué emails existen."""
    if hash_guardado is None:
        bcrypt.checkpw(clave.encode("utf-8"), _HASH_FICTICIO)
        return False
    return bcrypt.checkpw(clave.encode("utf-8"), hash_guardado.encode("ascii"))


def crear_token(usuario: Usuario) -> str:
    ahora = datetime.now(UTC)
    claims = {
        "sub": usuario.usuario_id,
        "empresa_id": usuario.empresa_id,
        "asesor_id": usuario.asesor_id,
        "rol": usuario.rol,
        "iat": ahora,
        "exp": ahora + DURACION_TOKEN,
    }
    return jwt.encode(claims, jwt_secret(), algorithm=ALGORITMO)


def usuario_actual(credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Usuario:
    """empresa_id sale de aquí, del token firmado, y de ningún otro lado."""
    no_autorizado = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "token ausente o inválido", headers={"WWW-Authenticate": "Bearer"}
    )
    if credenciales is None:
        raise no_autorizado
    try:
        claims = jwt.decode(credenciales.credentials, jwt_secret(), algorithms=[ALGORITMO])
    except jwt.PyJWTError:
        raise no_autorizado
    return Usuario(claims["sub"], claims["empresa_id"], claims["asesor_id"], claims["rol"])
