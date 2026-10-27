from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Node, NodeGrant, User
from .security import decode_session_token, hash_node_token

SESSION_COOKIE = "snackdrop_session"


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def user_from_token(db: Session, token: str | None, settings: Settings) -> User | None:
    if not token:
        return None
    payload = decode_session_token(token, settings)
    if not payload:
        return None
    try:
        user = db.get(User, int(payload["sub"]))
    except (TypeError, ValueError):
        return None
    if user is None or not user.is_active or user.token_version != payload.get("ver"):
        return None
    return user


def get_user_allow_pending(request: Request, db: Session = Depends(get_db)) -> User:
    """Usuario autenticado, aunque deba cambiar su contraseña."""
    user = user_from_token(db, request.cookies.get(SESSION_COOKIE), request.app.state.settings)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    return user


def get_current_user(user: User = Depends(get_user_allow_pending)) -> User:
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Se requiere rol de administrador")
    return user


def get_node_from_bearer(request: Request, db: Session = Depends(get_db)) -> Node:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    node = node_from_token(db, token)
    if node is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de nodo inválido")
    return node


def node_from_token(db: Session, token: str) -> Node | None:
    if not token or len(token) > 200:
        return None
    return db.scalar(select(Node).where(Node.token_hash == hash_node_token(token)))


# --- Reglas de acceso -------------------------------------------------------


def can_use_node(db: Session, user: User, node: Node) -> bool:
    if not user.is_active:
        return False
    if user.is_admin or node.owner_id == user.id or node.shared_with_all:
        return True
    return db.get(NodeGrant, (node.id, user.id)) is not None


def can_manage_node(user: User, node: Node) -> bool:
    return user.is_admin or node.owner_id == user.id
