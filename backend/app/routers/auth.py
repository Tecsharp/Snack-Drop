from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import SESSION_COOKIE, get_current_user, get_db, get_user_allow_pending
from ..models import User, utcnow
from ..security import (
    create_session_token,
    dummy_verify,
    hash_password,
    password_problem,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
    }


def set_session_cookie(response: Response, request: Request, user: User) -> None:
    settings = request.app.state.settings
    token = create_session_token(user.id, user.token_version, settings)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def client_ip(request: Request) -> str:
    # nginx coloca la IP real en X-Real-IP; el backend no se expone directamente.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limiter = request.app.state.login_limiter
    ip = client_ip(request)
    username = body.username.strip()
    if limiter.is_blocked(username, ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos fallidos. Intenta de nuevo en unos minutos."
        )
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        dummy_verify(body.password)
        ok = False
    else:
        ok = verify_password(user.password_hash, body.password) and user.is_active
    if not ok:
        limiter.record_failure(username, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos")
    limiter.reset(username)
    user.last_login_at = utcnow()
    db.commit()
    set_session_cookie(response, request, user)
    return user_out(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_user_allow_pending)):
    return user_out(user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(get_user_allow_pending),
    db: Session = Depends(get_db),
):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña actual no es correcta")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La nueva contraseña debe ser distinta")
    problem = password_problem(body.new_password, user.username)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    user = db.merge(user)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version += 1  # invalida otras sesiones
    db.commit()
    set_session_cookie(response, request, user)
    return user_out(user)


__all__ = ["router", "user_out", "get_current_user"]
