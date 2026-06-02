from fastapi import WebSocket
from typing import List, Dict
import json
import logging

logger = logging.getLogger("websocket")

class ConnectionManager:
    def __init__(self):
        # store_id -> list of WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, store_id: str):
        await websocket.accept()
        if store_id not in self.active_connections:
            self.active_connections[store_id] = []
        self.active_connections[store_id].append(websocket)
        logger.info(f"WebSocket client connected to store {store_id}")

    def disconnect(self, websocket: WebSocket, store_id: str):
        if store_id in self.active_connections:
            if websocket in self.active_connections[store_id]:
                self.active_connections[store_id].remove(websocket)
            if not self.active_connections[store_id]:
                del self.active_connections[store_id]
        logger.info(f"WebSocket client disconnected from store {store_id}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast_to_store(self, store_id: str, message: dict):
        if store_id in self.active_connections:
            dead_sockets = []
            for connection in self.active_connections[store_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"Error sending message to socket: {e}")
                    dead_sockets.append(connection)
            
            # Clean up dead sockets
            for dead in dead_sockets:
                self.disconnect(dead, store_id)

manager = ConnectionManager()
