"""WebSocket pour les commandes vocales."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/voice")
async def voice_commands(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_json()
            command = message.get("command", "")
            await websocket.send_json({"type": "command", "command": command})
    except WebSocketDisconnect:
        return
