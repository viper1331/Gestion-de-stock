"""WebSocket pour les événements de scan caméra."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/camera")
async def camera_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "ack", "payload": data})
    except WebSocketDisconnect:
        return
