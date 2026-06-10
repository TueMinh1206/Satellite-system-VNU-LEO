"""
api.py — VNU-LEO Python Bridge
──────────────────────────────
FastAPI server expose 2 module Python cho Svelte frontend:
  - /api/phased-array  : tính pattern từ anten.py (nhận el/az từ Svelte)
  - /api/handover      : nhận telemetry từ Svelte → chạy handover logic
  - /ws                : push handover events realtime về Svelte

Run: uvicorn api:app --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Import từ các module có sẵn ───────────────────────────────────────────────
from anten import (
    LinkBudget,
    get_weights,
    pattern_db,
)
from handover_engine import (
    HandoverConfig,
    HandoverEngine,
    ConnectionManager,
)

# ── Khởi tạo singleton ────────────────────────────────────────────────────────
lb         = LinkBudget()
cfg        = HandoverConfig()
ws_manager = ConnectionManager()
engine     = HandoverEngine(config=cfg, ws_manager=ws_manager)

ANGLES = np.linspace(-90, 90, 181)


# ── Lifespan: khởi động engine khi server start ───────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Tạo session mặc định cho router VNU khi server khởi động."""
    try:
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


# ══════════════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════════════

class TelemetryInput(BaseModel):
    """
    Dữ liệu Svelte gửi lên từ /api/satellites của index.js.
    Svelte lấy bestConn rồi POST sang đây.
    """
    satellite_id: str
    gateway:      str
    elevation:    float
    azimuth:      float
    range_km:     float
    cn:           float
    quality:      float
    latency:      float
    timestamp:    str


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Handover Events
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Svelte kết nối vào đây để nhận handover events realtime.
    Engine sẽ push: TELEMETRY, HANDOVER_START, HANDOVER_DONE
    """
    await ws_manager.connect(websocket)
    print(f"  [WS] Client connected — total: {ws_manager.client_count}")
    try:
        while True:
            # Giữ connection sống, nhận ping từ client nếu có
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
        print(f"  [WS] Client disconnected — total: {ws_manager.client_count}")


# ══════════════════════════════════════════════════════════════════════════════
# REST — Phased Array (anten.py)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/phased-array")
def get_phased_array(
    el:    float = 45.0,
    az:    float = 180.0,
    rain:  float = 20.0,
    N:     int   = 8,
    algo:  str   = "mvdr",
):
    """
    Svelte gọi endpoint này sau khi lấy el/az từ index.js.
    Trả về radiation pattern + link budget để vẽ trên dashboard.

    Params:
        el   : elevation (độ) — lấy từ bestConn.elevation của index.js
        az   : azimuth (độ)   — lấy từ bestConn.azimuth của index.js
        rain : lượng mưa mm/h (mặc định 20)
        N    : số phần tử anten (mặc định 8)
        algo : conv | mvdr | lms | rls
    """
    # Tính range từ elevation (slant range xấp xỉ)
    alt_m   = 550_000  # 550 km — altitude chòm sao
    el_rad  = math.radians(max(el, 1.0))
    range_m = alt_m / math.sin(el_rad)

    # Link budget
    budget = lb.compute(range_m, el, rain_mmh=rain)

    # Beamforming
    theta0  = 90.0 - el          # steering angle từ boresight
    theta_j = theta0 + 25.0      # góc nhiễu giả định
    snr     = max(budget["CN_db"], 3.0)

    w   = get_weights(algo, N, theta0, theta_j, 0.05, snr)
    pat = pattern_db(ANGLES, w, N)

    phases = (np.angle(w) * 180 / np.pi).tolist()
    amps   = np.abs(w)
    amps   = (amps / (amps.max() + 1e-12)).tolist()

    return {
        "angles":      ANGLES.tolist(),
        "pattern":     pat.tolist(),
        "phases":      phases,
        "amplitudes":  amps,
        "budget":      budget,
        "params": {
            "elevation": el,
            "azimuth":   az,
            "N":         N,
            "algo":      algo,
            "range_km":  round(range_m / 1000, 1),
            "theta0":    round(theta0, 2),
            "theta_j":   round(theta_j, 2),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# REST — Nhận Telemetry từ Svelte → cập nhật Handover Engine
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/telemetry")
async def receive_telemetry(data: TelemetryInput):
    """
    Svelte POST bestConn data từ index.js vào đây mỗi 5 giây.
    Engine cập nhật trạng thái vệ tinh hiện tại và kiểm tra
    xem có cần handover không.

    Flow:
        index.js → Svelte poll → Svelte POST /api/telemetry
                                         ↓
                               handover_engine cập nhật
                                         ↓
                               /ws broadcast nếu có event
    """
    session = engine.sessions.get("VNU-Router")
    if not session:
        # Tạo lại session nếu chưa có
        try:
            await engine.add_session("VNU-Router", 21.03, 105.85)
            session = engine.sessions.get("VNU-Router")
        except Exception as e:
            return {"status": "error", "message": str(e)}

    if session:
        # Cập nhật thông số vệ tinh hiện tại từ data index.js gửi xuống
        sat = session.current_satellite
        sat.elevation      = data.elevation
        sat.azimuth        = data.azimuth
        sat.cn_db          = data.cn
        sat.slant_range_km = data.range_km

        # Broadcast telemetry realtime qua WebSocket
        await engine._broadcast_event(session, "TELEMETRY")

    return {
        "status":  "ok",
        "session": session.state.value if session else "unknown",
        "handover_count": session.handover_count if session else 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# REST — Gateway + Session status (cho NMS dashboard)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/gateway-status")
def get_gateway_status():
    """Trạng thái các gateway — merge với data từ handover engine."""
    return engine.gateway_status()


@app.get("/api/session-summary")
def get_session_summary():
    """Tóm tắt session — handover count, avg latency, bytes transferred."""
    return engine.session_summary()


@app.get("/api/handover-history")
def get_handover_history():
    """Lịch sử handover của session VNU-Router."""
    session = engine.sessions.get("VNU-Router")
    if not session:
        return []
    return session.handover_history[-50:]


@app.get("/health")
def health():
    return {
        "status":       "ok",
        "ws_clients":   ws_manager.client_count,
        "sessions":     len(engine.sessions),
        "time":         time.strftime("%H:%M:%S"),
    }