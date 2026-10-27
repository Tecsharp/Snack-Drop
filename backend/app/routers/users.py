from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db, require_admin
from ..models import Job, User, iso
from ..storage import remove_job_dir
from ..security import generate_password, hash_password, password_problem

router = APIRouter(prefix="/api/users", tags=["users"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    role: Literal["admin", "user"] = "user"
    password: str | None = Field(None, max_length=256)


class UserPatch(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


def admin_user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "is_active": u.is_active,
        "must_change_password": u.must_change_password,
        "created_at": iso(u.created_at),
        "last_login_at": iso(u.last_login_at),
    }


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))


@router.get("")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [admin_user_out(u) for u in db.scalars(select(User).order_by(User.username)).all()]


@router.post("", status_code=201)
def create_user(body: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Usuario inválido: 3-32 caracteres (letras, números, . _ -)")
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise HTTPException(409, "El usuario ya existe")
    temp = None
    if body.password:
        problem = password_problem(body.password, username)
        if problem:
            raise HTTPException(400, problem)
        password = body.password
    else:
        password = temp = generate_password()
    user = User(
        username=username,
        role=body.role,
        password_hash=hash_password(password),
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    return {"user": admin_user_out(user), "temporary_password": temp}


@router.patch("/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    demoting = (body.role == "user" and user.role == "admin") or (body.is_active is False and user.is_admin)
    if demoting and user.is_active and _active_admins(db) <= 1:
        raise HTTPException(400, "Debe existir al menos un administrador activo")
    if user.id == admin.id and (body.is_active is False or body.role == "user"):
        raise HTTPException(400, "No puedes desactivarte ni quitarte el rol de administrador")
    changed = False
    if body.role is not None and body.role != user.role:
        user.role = body.role
        changed = True
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        changed = True
    if changed:
        user.token_version += 1
    db.commit()
    return admin_user_out(user)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    temp = generate_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.token_version += 1
    db.commit()
    return {"user": admin_user_out(user), "temporary_password": temp}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    if user.id == admin.id:
        raise HTTPException(400, "No puedes eliminar tu propia cuenta")
    if user.is_admin and user.is_active and _active_admins(db) <= 1:
        raise HTTPException(400, "Debe existir al menos un administrador activo")
    job_ids = list(db.scalars(select(Job.id).where(Job.owner_id == user.id)))
    db.delete(user)
    db.commit()
    for job_id in job_ids:
        remove_job_dir(request.app.state.settings, job_id)
