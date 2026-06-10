"""
api/server.py
─────────────
FastAPI WebSocket server — cầu nối giữa Python simulation và SvelteKit dashboard.

Endpoints:
  GET  /            → health check
  GET  /gateways    → trạng thái 3 gateway (JSON)
  GET  /sessions    → tóm tắt tất cả phiên (JSON)
  POST /sessions    → tạo phiên kết nối mới
  WS   /ws          → real-time telemetry stream (JSON frames mỗi 1s)

Khởi động:
    uvicorn Gateway.server:app --host 0.0.0.0 --port 8000 --reload

Kết nối từ SvelteKit:
    const ws = new WebSocket('ws://localhost:8000/ws')
    ws.onmessage = (e) => { const frame = JSON.parse(e.data); updateUI(frame) }
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .handover_engine import (
    ConnectionManager, HandoverConfig, HandoverEngine, GATEWAYS,
)


# ── Khởi động ứng dụng ────────────────────────────────────────────────────────

ws_manager = ConnectionManager()
config     = HandoverConfig()
engine     = HandoverEngine(config=config, ws_manager=ws_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Tạo 3 phiên mẫu khi server khởi động để dashboard có dữ liệu ngay."""
    default_users = [
        ("Demo-HN",  21.03, 105.85),
        ("Demo-DN",  16.07, 108.22),
        ("Demo-HCM", 10.82, 106.63),
    ]
    for uid, lat, lon in default_users:
        try:
            await engine.add_session(uid, lat, lon)
        except Exception as e:
            print(f"Không thể tạo session {uid}: {e}")
    yield  # Server chạy
    # Cleanup (nếu cần)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="VNU-LEO Gateway API",
    description="Tầng 2: Gateway & Handover Simulator — REST + WebSocket",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — cho phép SvelteKit (localhost:5173) kết nối
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    """Body để tạo phiên kết nối mới qua POST /sessions."""
    user_id:  str
    user_lat: float = 16.0   # Mặc định Đà Nẵng
    user_lon: float = 108.0


class ConfigUpdate(BaseModel):
    """Body để cập nhật cấu hình động qua PUT /config."""
    elev_warn_deg:        float | None = None
    elev_critical_deg:    float | None = None
    cn_warn_db:           float | None = None
    cn_critical_db:       float | None = None
    alpha_elevation:      float | None = None
    beta_cn:              float | None = None
    prediction_horizon_s: float | None = None


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def health_check():
    """Health check — dùng để test server đang chạy."""
    return {
        "status":    "ok",
        "service":   "VNU-LEO Gateway API",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ws_clients": ws_manager.client_count,
        "sessions":  len(engine.sessions),
    }


@app.get("/gateways")
async def get_gateways():
    """
    Trạng thái 3 gateway.
    Dashboard dùng endpoint này để vẽ map trạng thái ALIVE/DEAD.
    """
    return {
        "gateways":  engine.gateway_status(),
        "timestamp": time.time(),
    }


@app.get("/sessions")
async def get_sessions():
    """Tóm tắt tất cả phiên đang hoạt động."""
    return {
        "sessions":  engine.session_summary(),
        "count":     len(engine.sessions),
        "timestamp": time.time(),
    }


@app.post("/sessions", status_code=201)
async def create_session(body: SessionCreate):
    """
    Tạo phiên kết nối mới.

    Example:
        curl -X POST http://localhost:8000/sessions \\
             -H 'Content-Type: application/json' \\
             -d '{"user_id":"User-01","user_lat":21.03,"user_lon":105.85}'
    """
    if body.user_id in engine.sessions:
        raise HTTPException(status_code=409,
                            detail=f"user_id '{body.user_id}' đã tồn tại")

    if not (8.0 <= body.user_lat <= 24.0 and 101.0 <= body.user_lon <= 110.5):
        raise HTTPException(status_code=400,
                            detail="Tọa độ ngoài phạm vi Việt Nam")

    try:
        session = await engine.add_session(body.user_id, body.user_lat, body.user_lon)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {"status": "created", "session": session.summary()}


@app.put("/config")
async def update_config(body: ConfigUpdate):
    """
    Cập nhật cấu hình handover engine tại runtime (không cần restart).
    Tiện cho báo cáo: thầy có thể thay đổi ngưỡng và xem ảnh hưởng ngay.
    """
    cfg = engine.cfg
    if body.elev_warn_deg        is not None: cfg.elev_warn_deg        = body.elev_warn_deg
    if body.elev_critical_deg    is not None: cfg.elev_critical_deg    = body.elev_critical_deg
    if body.cn_warn_db           is not None: cfg.cn_warn_db           = body.cn_warn_db
    if body.cn_critical_db       is not None: cfg.cn_critical_db       = body.cn_critical_db
    if body.alpha_elevation      is not None: cfg.alpha_elevation      = body.alpha_elevation
    if body.beta_cn              is not None: cfg.beta_cn              = body.beta_cn
    if body.prediction_horizon_s is not None: cfg.prediction_horizon_s = body.prediction_horizon_s

    return {
        "status": "updated",
        "config": {
            "elev_warn_deg":        cfg.elev_warn_deg,
            "elev_critical_deg":    cfg.elev_critical_deg,
            "cn_warn_db":           cfg.cn_warn_db,
            "cn_critical_db":       cfg.cn_critical_db,
            "alpha_elevation":      cfg.alpha_elevation,
            "beta_cn":              cfg.beta_cn,
            "prediction_horizon_s": cfg.prediction_horizon_s,
        },
    }


@app.get("/handover-history/{user_id}")
async def get_handover_history(user_id: str):
    """Lịch sử handover của một user — dùng cho Optional 3 Dashboard."""
    if user_id not in engine.sessions:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy '{user_id}'")
    session = engine.sessions[user_id]
    return {
        "user_id": user_id,
        "handover_count": session.handover_count,
        "avg_latency_ms": round(session.avg_latency_ms, 1),
        "history": session.handover_history,
    }


# ── WebSocket Endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket real-time telemetry stream.

    Client (SvelteKit) nhận JSON frames mỗi 1 giây:
    {
      "user_id":        "Demo-HN",
      "timestamp":      1700000000.0,
      "state":          "CONNECTED",
      "satellite_id":   "VNU-03",
      "gateway_name":   "Hà Nội",
      "elevation":      52.3,
      "azimuth":        185.0,
      "cn_db":          18.5,
      "signal_quality": "EXCELLENT",
      "slant_range_km": 712.0,
      "handover_count": 2,
      "bytes_transferred": 45000000,
      "uptime_s":       120.0,
      "event_type":     "TELEMETRY"
    }

    Kết nối từ SvelteKit:
        import { onMount } from 'svelte'
        let ws
        onMount(() => {
          ws = new WebSocket('ws://localhost:8000/ws')
          ws.onmessage = (e) => {
            const frame = JSON.parse(e.data)
            // Cập nhật store
          }
          return () => ws.close()
        })
    """
    await ws_manager.connect(websocket)
    try:
        # Gửi snapshot ngay khi client kết nối
        import json, time as _time
        snapshot = {
            "event_type": "SNAPSHOT",
            "sessions":   engine.session_summary(),
            "gateways":   engine.gateway_status(),
            "timestamp":  _time.time(),
        }
        await websocket.send_text(json.dumps(snapshot, ensure_ascii=False))

        # Giữ kết nối — nhận ping từ client (optional)
        while True:
            try:
                data = await websocket.receive_text()
                # Client có thể gửi {"type":"ping"} để giữ connection
                if data == '{"type":"ping"}':
                    await websocket.send_text('{"type":"pong"}')
            except WebSocketDisconnect:
                break
    finally:
        await ws_manager.disconnect(websocket)
