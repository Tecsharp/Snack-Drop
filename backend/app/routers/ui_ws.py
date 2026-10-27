from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..deps import SESSION_COOKIE, user_from_token
from ..realtime import UIConn

router = APIRouter()


def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return False
    host = ws.headers.get("x-forwarded-host") or ws.headers.get("host", "")
    return urlparse(origin).netloc == host


@router.websocket("/ws/ui")
async def ui_socket(ws: WebSocket):
    app = ws.app
    # Protección contra Cross-Site WebSocket Hijacking.
    if not _same_origin(ws):
        await ws.close(code=4403)
        return
    db = app.state.SessionLocal()
    try:
        user = user_from_token(db, ws.cookies.get(SESSION_COOKIE), app.state.settings)
        if user is None or user.must_change_password:
            await ws.close(code=4401)
            return
        user_id = user.id
    finally:
        db.close()
    await ws.accept()
    conn = UIConn(ws=ws, user_id=user_id)
    hub = app.state.hub
    hub.ui.add(conn)
    await conn.send({"type": "hello", "user_id": user_id})
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await conn.send({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.ui.discard(conn)
