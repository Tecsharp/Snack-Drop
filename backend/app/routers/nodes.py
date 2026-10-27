from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import can_manage_node, can_use_node, get_current_user, get_db
from ..models import Job, Node, NodeGrant, User, utcnow
from ..security import generate_node_token, hash_node_token

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


class NodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    shared_with_all: bool = False


class NodePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    is_paused: bool | None = None
    shared_with_all: bool | None = None


class GrantIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


def _hub(request: Request):
    return request.app.state.hub


def _get_manageable(db: Session, user: User, node_id: int) -> Node:
    node = db.get(Node, node_id)
    if node is None or not can_use_node(db, user, node):
        raise HTTPException(404, "Nodo no encontrado")
    if not can_manage_node(user, node):
        raise HTTPException(403, "Solo el dueño del nodo o un administrador pueden modificarlo")
    return node


def _install_info(request: Request, token: str) -> dict:
    origin = f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"
    return {
        "token": token,
        "server_url": origin,
        "docker_command": f"./setup-worker.sh --server {origin} --token {token}",
        "python_command": (
            f"SNACKDROP_SERVER={origin} SNACKDROP_TOKEN={token} python -m snackdrop_worker"
        ),
    }


@router.get("")
def list_nodes(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    hub = _hub(request)
    nodes = db.scalars(select(Node).order_by(Node.kind, Node.name)).all()
    return [hub.node_out(db, n, user) for n in nodes if can_use_node(db, user, n)]


@router.post("", status_code=201)
async def create_node(
    body: NodeCreate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    token = generate_node_token()
    node = Node(
        name=body.name.strip(),
        owner_id=user.id,
        token_hash=hash_node_token(token),
        shared_with_all=body.shared_with_all and user.is_admin,
        capabilities=[],
    )
    db.add(node)
    db.commit()
    hub = _hub(request)
    await hub.notify_node(db, node)
    return {"node": hub.node_out(db, node, user), "install": _install_info(request, token)}


@router.patch("/{node_id}")
async def patch_node(
    node_id: int,
    body: NodePatch,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    node = _get_manageable(db, user, node_id)
    if body.name is not None:
        node.name = body.name.strip()
    if body.is_paused is not None:
        node.is_paused = body.is_paused
    if body.shared_with_all is not None:
        if not user.is_admin:
            raise HTTPException(403, "Solo un administrador puede compartir un nodo con todos")
        node.shared_with_all = body.shared_with_all
    db.commit()
    hub = _hub(request)
    await hub.notify_node(db, node)
    if not node.is_paused:
        await hub.dispatch()
    return hub.node_out(db, node, user)


@router.post("/{node_id}/rotate-token")
async def rotate_token(
    node_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    node = _get_manageable(db, user, node_id)
    token = generate_node_token()
    node.token_hash = hash_node_token(token)
    db.commit()
    conn = _hub(request).nodes.get(node.id)
    if conn is not None:
        try:
            await conn.ws.close(code=4401)
        except Exception:  # noqa: BLE001
            pass
    return {"node": _hub(request).node_out(db, node, user), "install": _install_info(request, token)}


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    node = _get_manageable(db, user, node_id)
    if node.kind == "master":
        raise HTTPException(400, "El nodo maestro se administra desde la configuración del servidor")
    hub = _hub(request)
    targeted = db.scalars(select(Job).where(Job.target_node_id == node.id, Job.status == "queued")).all()
    for job in targeted:
        job.status = "cancelled"
        job.message = "El nodo destino fue eliminado"
        job.finished_at = utcnow()
    conn = hub.nodes.pop(node.id, None)
    db.delete(node)
    db.commit()
    if conn is not None:
        try:
            await conn.ws.close(code=4404)
        except Exception:  # noqa: BLE001
            pass
    for job in targeted:
        await hub.notify_job(db, job)
    await hub.notify_node_removed(node_id)


@router.post("/{node_id}/grants", status_code=201)
async def add_grant(
    node_id: int,
    body: GrantIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    node = _get_manageable(db, user, node_id)
    target = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))
    if target is None or not target.is_active:
        raise HTTPException(404, "Usuario no encontrado")
    if target.id == node.owner_id:
        raise HTTPException(400, "El dueño ya tiene acceso")
    if db.get(NodeGrant, (node.id, target.id)) is None:
        db.add(NodeGrant(node_id=node.id, user_id=target.id))
        db.commit()
        db.refresh(node)
    hub = _hub(request)
    await hub.notify_node(db, node)
    await hub.dispatch()
    return hub.node_out(db, node, user)


@router.delete("/{node_id}/grants/{user_id}")
async def remove_grant(
    node_id: int,
    user_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    node = _get_manageable(db, user, node_id)
    grant = db.get(NodeGrant, (node.id, user_id))
    if grant is not None:
        db.delete(grant)
        db.commit()
        db.refresh(node)
    hub = _hub(request)
    await hub.notify_node_removed(node.id)  # el usuario revocado deja de verlo
    await hub.notify_node(db, node)
    return hub.node_out(db, node, user)
