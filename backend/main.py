from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.routers import events, metrics, funnel, heatmap, anomalies, health
from backend.middleware.logging import StructuredLoggingMiddleware
from backend.websocket.manager import manager
from fastapi.staticfiles import StaticFiles
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.main")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for real-time retail visitor analytics using YOLOv8 & ByteTrack",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Structured JSON Logging
app.add_middleware(StructuredLoggingMiddleware)

# Include Routers
app.include_router(events.router)
app.include_router(metrics.router)
app.include_router(funnel.router)
app.include_router(heatmap.router)
app.include_router(anomalies.router)
app.include_router(health.router)

# Mount dashboard UI static files conditionally to prevent crashes when folder isn't in context
import os
dashboard_path = "dashboard"
if os.path.exists(dashboard_path):
    app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")
elif os.path.exists("../dashboard"):
    app.mount("/dashboard", StaticFiles(directory="../dashboard", html=True), name="dashboard")
else:
    logger.warning("Dashboard directory not found. Skipping static file mount.")

@app.websocket("/ws/stores/{id}/live")
async def websocket_endpoint(websocket: WebSocket, id: str):
    await manager.connect(websocket, id)
    try:
        while True:
            try:
                # Wait briefly for incoming client message
                data = await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
            except asyncio.TimeoutError:
                # Send a ping every 20s to keep connection alive in browser
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        manager.disconnect(websocket, id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket, id)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up RetailIQ Backend API...")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down RetailIQ Backend API...")
