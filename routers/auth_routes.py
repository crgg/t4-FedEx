"""
Endpoint de emisión de tokens (OAuth2 password flow).

Público por diseño: es el punto donde el cliente cambia credenciales
por un JWT. Usa form-data `username` / `password`.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from auth import ACCESS_TOKEN_EXPIRE_MINUTES, Token, authenticate_user, create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(
        access_token=create_access_token(subject=user.username),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
