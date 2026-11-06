"""
Autenticación JWT del microservicio.

- Hash/verificación de contraseñas con passlib[bcrypt].
- Emisión de access tokens firmados con PyJWT (con expiración).
- Dependencia `verify_token` / `get_current_user` para proteger endpoints.

No depende de main.py ni de los routers, así que puede importarse desde
cualquier parte sin crear dependencias circulares.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from pydantic import BaseModel

load_dotenv()

# ---- CONFIGURACIÓN ----
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Usuario de servicio (credenciales para obtener tokens vía /auth/token)
AUTH_USERNAME = os.getenv("AUTH_USERNAME")
AUTH_PASSWORD_HASH = os.getenv("AUTH_PASSWORD_HASH")

_missing = [name for name, value in {
    "SECRET_KEY": SECRET_KEY,
    "AUTH_USERNAME": AUTH_USERNAME,
    "AUTH_PASSWORD_HASH": AUTH_PASSWORD_HASH,
}.items() if not value]
if _missing:
    raise RuntimeError(f"Faltan variables de entorno en .env: {', '.join(_missing)}")

if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY es demasiado corta: usa al menos 32 caracteres aleatorios")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Extrae el token del header `Authorization: Bearer <token>`.
# Si el header falta, FastAPI responde automáticamente 401.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ---- ESQUEMAS ----
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUser(BaseModel):
    username: str
    store_id: Optional[int] = None  # Tenant del token (siempre presente tras verify_token)


# ---- CONTRASEÑAS ----
def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(username: str, password: str) -> Optional[CurrentUser]:
    """Valida las credenciales contra el usuario de servicio definido en .env."""
    if username != AUTH_USERNAME:
        # Se verifica igualmente un hash para no filtrar por tiempo de respuesta
        # si el usuario existe o no.
        pwd_context.dummy_verify()
        return None
    if not verify_password(password, AUTH_PASSWORD_HASH):
        return None
    return CurrentUser(username=username)


# ---- TOKENS ----
def create_access_token(subject: str, store_id: int, expires_delta: Optional[timedelta] = None) -> str:
    """Emite un JWT ligado a un tenant: `store_id` es obligatorio."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "store_id": store_id, "iat": now, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _credentials_exception(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---- DEPENDENCIA DE FASTAPI ----
async def verify_token(request: Request, token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """Valida firma y vigencia del JWT, extrae el tenant y retorna el usuario.

    El `store_id` queda disponible de dos formas:
      - `request.state.store_id` (para dependencias que solo reciben el Request)
      - en el `CurrentUser` devuelto (`Depends(get_current_user)` en la ruta)
    """
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "store_id"]},
        )
    except jwt.ExpiredSignatureError:
        raise _credentials_exception("Token expirado")
    except jwt.InvalidTokenError:
        # Incluye tokens antiguos emitidos sin store_id
        raise _credentials_exception("Token inválido")

    store_id = payload["store_id"]
    if not isinstance(store_id, int) or isinstance(store_id, bool):
        raise _credentials_exception("Token inválido: store_id mal formado")

    request.state.store_id = store_id
    return CurrentUser(username=payload["sub"], store_id=store_id)


# Alias semántico para endpoints que necesiten el usuario
get_current_user = verify_token
