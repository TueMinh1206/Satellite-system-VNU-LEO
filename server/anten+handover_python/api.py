"""
api.py — VNU-LEO Python Bridge
Updated to receive gateways view from Svelte.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import asynccontextmanager
from typing import Any, List, Dict

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import from local modules
from anten import LinkBudget, get_weights, pattern_db
from handover_engine import HandoverConfig, HandoverEngine, ConnectionManager


# ── Singleton instances ──────────────────────────────────────────────
lb = LinkBudget()
cfg = HandoverConfig()
ws_manager = ConnectionManager()
engine = HandoverEngine(config=cfg, ws_manager=ws_manager)

ANGLES = np.linspace(-90, 90, 181)


# ── Lifespan ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create default session for VNU router at startup."""
    try:
        # Hanoi coordinates (router location)
        await engine.add_session("VNU-Router", 21.03, 105.85)
        print("  [OK] HandoverEngine started — VNU-Router session active")
    except Exception as e:
        print(f"  [WARN] HandoverEngine start failed: {e}")
    yield
    print("  [INFO] Server shutting down")


app = FastAPI(title="VNU-LEO Python Bridge", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════════════
# MODELS
# ═════════════════════════════════════════════════════════════════════

class TelemetryInput(BaseModel):
    """Data from Svelte: best satellite + gateways view for that satellite."""
    satellite_id: str
    elevation: float
    azimuth: float
    range_km: float
    cn: float
    gateways: List[Dict[str, Any]]   # each: {name, elevation, cn, ...}


# ═════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    print(f"  [WS] Client connected — total: {ws_manager.client_count}")
    try:
        while True:
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
        print(f"  [WS] Client disconnected — total: {ws_manager.client_count}")


# ═════════════════════════════════════════════════════════════════════
# REST — Phased Array (anten.py)
# ═════════════════════════════════════════════════════════════════════

@app.get("/api/phased-array")
def get_phased_array(
    el: float = 45.0,
    az: float = 180.0,
    rain: float = 20.0,
    N: int = 8,
    algo: str = "mvdr",
):
    alt_m = 550_000
    el_rad = math.radians(max(el, 1.0))
    range_m = alt_m / math.sin(el_rad)

    budget = lb.compute(range_m, el, rain_mmh=rain)

    theta0 = 90.0 - el
    theta_j = theta0 + 25.0
    snr = max(budget["CN_db"], 3.0)

    w = get_weights(algo, N, theta0, theta_j, 0.05, snr)
    pat = pattern_db(ANGLES, w, N)

    phases = (np.angle(w) * 180 / np.pi).tolist()
    amps = np.abs(w)
    amps = (amps / (amps.max() + 1e-12)).tolist()

    return {
        "angles": ANGLES.tolist(),
        "pattern": pat.tolist(),
        "phases": phases,
        "amplitudes": amps,
        "budget": budget,
        "params": {
            "elevation": el,
            "azimuth": az,
            "N": N,
            "algo": algo,
            "range_km": round(range_m / 1000, 1),
            "theta0": round(theta0, 2),
            "theta_j": round(theta_j, 2),
        },
    }


# ═════════════════════════════════════════════════════════════════════
# REST — Telemetry (updates handover engine)
# ═════════════════════════════════════════════════════════════════════

@app.post("/api/telemetry")
async def receive_telemetry(data: TelemetryInput):
    session = engine.sessions.get("VNU-Router")
    if not session:
        try:
            await engine.add_session("VNU-Router", 21.03, 105.85)
            session = engine.sessions.get("VNU-Router")
        except Exception as e:
            return {"status": "error", "message": str(e)}

    if session:
        # Update satellite data and gateway list
        engine.update_satellite_and_gateways(
            user_id="VNU-Router",
            satellite_id=data.satellite_id,
            elevation=data.elevation,
            azimuth=data.azimuth,
            cn_db=data.cn,
            range_km=data.range_km,
            gateways_view=data.gateways
        )
        await engine._broadcast_event(session, "TELEMETRY")

    return {
        "status": "ok",
        "session": session.state.value if session else "unknown",
        "handover_count": session.handover_count if session else 0,
        "selected_gateway": session.gateway.name if session else None,
    }


# ═════════════════════════════════════════════════════════════════════
# REST — Gateway status, session summary, handover history
# ═════════════════════════════════════════════════════════════════════

@app.get("/api/gateway-status")
def get_gateway_status():
    return engine.gateway_status()

@app.get("/api/session-summary")
def get_session_summary():
    return engine.session_summary()

@app.get("/api/handover-history")
def get_handover_history():
    session = engine.sessions.get("VNU-Router")
    if not session:
        return []
    return session.handover_history[-50:]

@app.get("/health")
def health():
    return {
        "status": "ok",
        "ws_clients": ws_manager.client_count,
        "sessions": len(engine.sessions),
        "time": time.strftime("%H:%M:%S"),
    }