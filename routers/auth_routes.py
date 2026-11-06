"""
Endpoint de emisión de tokens (OAuth2 password flow).

Público por diseño: es el punto donde el cliente cambia credenciales
por un JWT. Usa form-data `username` / `password` / `store_id`.

Multi-tenant: el token queda ligado a una tienda (`store_id`), que debe
existir en la tabla `stores`.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from auth import ACCESS_TOKEN_EXPIRE_MINUTES, Token, authenticate_user, create_access_token
from dependencies import get_db
from models import Store

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    store_id: int = Form(..., gt=0, description="Tienda (tenant) para la que se emite el token"),
    session: AsyncSession = Depends(get_db),
):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    store = await session.get(Store, store_id)
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tienda {store_id} no encontrada")

    return Token(
        access_token=create_access_token(subject=user.username, store_id=store_id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
