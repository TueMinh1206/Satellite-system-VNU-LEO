"""
handover_engine.py — Thuần Python, không phụ thuộc tọa độ gateway.
Nhận danh sách gateway từ telemetry, tự chọn gateway tốt nhất.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


# ═════════════════════════════════════════════════════════════════════
# Định nghĩa dữ liệu cơ bản
# ═════════════════════════════════════════════════════════════════════

class SessionState(Enum):
    CONNECTED = "connected"
    HANDOVER = "handover"
    SEARCHING = "searching"
    DISCONNECTED = "disconnected"

class HandoverType(Enum):
    INTRA_GATEWAY = "intra_gateway"
    INTER_GATEWAY = "inter_gateway"

@dataclass
class Gateway:
    name: str
    status: str = "Alive"
    active_sessions: int = 0
    total_handovers: int = 0

@dataclass
class Satellite:
    id: str
    elevation: float = 0.0
    azimuth: float = 0.0
    cn_db: float = 0.0
    slant_range_km: float = 0.0
    serving_gateway: str = ""
    signal_quality: float = 0.0

@dataclass
class UserSession:
    user_id: str
    current_satellite: Satellite
    gateway: Gateway
    user_lat: float = 0.0
    user_lon: float = 0.0
    state: SessionState = SessionState.CONNECTED
    handover_count: int = 0
    handover_history: List[Dict] = field(default_factory=list)
    bytes_transferred: int = 0
    start_time: float = field(default_factory=time.time)
    last_gateways_view: List[Dict] = field(default_factory=list)  # store latest gateways view

    @property
    def uptime_s(self) -> float:
        return time.time() - self.start_time

    @property
    def avg_latency_ms(self) -> float:
        if not self.handover_history:
            return 0.0
        return sum(h.get("latency_ms", 0) for h in self.handover_history) / len(self.handover_history)

    def record_handover(self, old_sat: Satellite, new_sat: Satellite,
                        new_gw: Gateway, latency_ms: float, ho_type: HandoverType):
        entry = {
            "timestamp": time.time(),
            "from_sat": old_sat.id,
            "to_sat": new_sat.id,
            "from_gw": self.gateway.name,
            "to_gw": new_gw.name,
            "latency_ms": latency_ms,
            "type": ho_type.value,
        }
        self.handover_history.append(entry)
        self.handover_count += 1

    def summary(self) -> Dict:
        return {
            "user_id": self.user_id,
            "gateway": self.gateway.name,
            "satellite": self.current_satellite.id,
            "state": self.state.value,
            "handover_count": self.handover_count,
            "uptime_s": round(self.uptime_s, 1),
            "bytes_mb": round(self.bytes_transferred / 1e6, 2),
        }

@dataclass
class TelemetryFrame:
    user_id: str
    timestamp: float
    state: str
    satellite_id: str
    gateway_name: str
    elevation: float
    azimuth: float
    cn_db: float
    signal_quality: float
    slant_range_km: float
    handover_count: int
    bytes_transferred: int
    uptime_s: float
    event_type: str

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "type": self.event_type,
            "state": self.state,
            "satellite_id": self.satellite_id,
            "gateway": self.gateway_name,
            "elevation": self.elevation,
            "azimuth": self.azimuth,
            "cn_db": self.cn_db,
            "signal_quality": self.signal_quality,
            "range_km": self.slant_range_km,
            "handover_count": self.handover_count,
            "bytes_transferred": self.bytes_transferred,
            "uptime_s": round(self.uptime_s, 1),
        }


# ═════════════════════════════════════════════════════════════════════
# Cấu hình Handover
# ═════════════════════════════════════════════════════════════════════

@dataclass
class HandoverConfig:
    elev_warn_deg: float = 25.0
    elev_critical_deg: float = 15.0
    elev_min_deg: float = 5.0
    cn_warn_db: float = 8.0
    cn_critical_db: float = 5.0
    pre_establish_ms: float = 30.0
    switch_time_ms: float = 20.0
    release_time_ms: float = 10.0
    monitor_interval_s: float = 1.0
    alpha_elevation: float = 0.4
    beta_cn: float = 0.6

    @property
    def total_ho_time_ms(self) -> float:
        return self.pre_establish_ms + self.switch_time_ms + self.release_time_ms


# ═════════════════════════════════════════════════════════════════════
# WebSocket Connection Manager
# ═════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self._clients: Set[Any] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws):
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws):
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, data: dict):
        if not self._clients:
            return
        msg = json.dumps(data, ensure_ascii=False)
        dead = set()
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._lock:
                self._clients -= dead

    @property
    def client_count(self) -> int:
        return len(self._clients)


# ═════════════════════════════════════════════════════════════════════
# Handover Engine (Core)
# ═════════════════════════════════════════════════════════════════════

class HandoverEngine:
    def __init__(self,
                 config: Optional[HandoverConfig] = None,
                 ws_manager: Optional[ConnectionManager] = None):
        self.cfg = config or HandoverConfig()
        self.ws_manager = ws_manager
        self.sessions: Dict[str, UserSession] = {}
        self.event_log: List[Dict] = []
        self._monitor_tasks: Dict[str, asyncio.Task] = {}

    # ── Helper: Chọn gateway tốt nhất từ danh sách gateways_view ─────────────
    def _select_best_gateway(self, gateways_view: List[dict]) -> str:
        best_name = "Unknown"
        best_score = -1e9
        for gw in gateways_view:
            # Bỏ qua gateway không thấy vệ tinh
            if gw.get('elevation', -90) < self.cfg.elev_min_deg:
                continue
            # Điểm số: alpha*elevation + beta*cn
            score = self.cfg.alpha_elevation * gw['elevation'] + self.cfg.beta_cn * gw['cn']
            if score > best_score:
                best_score = score
                best_name = gw['name']
        return best_name

    # ── Public method: cập nhật dữ liệu từ telemetry (Node.js qua Svelte) ────
    def update_satellite_and_gateways(self, user_id: str,
                                       satellite_id: str,
                                       elevation: float,
                                       azimuth: float,
                                       cn_db: float,
                                       range_km: float,
                                       gateways_view: List[dict]) -> bool:
        session = self.sessions.get(user_id)
        if not session:
            return False

        # Lưu lại gateways_view cho session (có thể dùng khi handover)
        session.last_gateways_view = gateways_view

        # Cập nhật thông tin vệ tinh
        sat = session.current_satellite
        sat.id = satellite_id
        sat.elevation = elevation
        sat.azimuth = azimuth
        sat.cn_db = cn_db
        sat.slant_range_km = range_km

        # Tính signal_quality (0-100)
        norm_cn = min(100, max(0, (cn_db + 10) * 4))
        norm_el = min(100, max(0, elevation * 2))
        sat.signal_quality = (norm_cn + norm_el) / 2

        # Chọn gateway tốt nhất từ danh sách
        selected_gw_name = self._select_best_gateway(gateways_view)
        if session.gateway.name != selected_gw_name:
            old_gw = session.gateway
            new_gw = Gateway(name=selected_gw_name)
            session.gateway = new_gw
            old_gw.active_sessions = max(0, old_gw.active_sessions - 1)
            new_gw.active_sessions += 1
            self._log("INFO", user_id, f"Gateway chọn bởi engine: {old_gw.name} → {new_gw.name}")
        sat.serving_gateway = selected_gw_name
        return True

    # ── Internal logging ─────────────────────────────────────────────────────
    def _log(self, level: str, user_id: str, msg: str) -> Dict:
        icons = {"INFO": "ℹ️", "WARN": "⚠️", "HANDOVER": "🔄",
                 "ERROR": "❌", "CONNECT": "🟢", "DISCONNECT": "🔴"}
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "user_id": user_id,
            "msg": msg,
        }
        self.event_log.append(entry)
        print(f"{icons.get(level, '•')} [{entry['time']}] [{user_id}] {msg}")
        return entry

    # ── Broadcast helper ─────────────────────────────────────────────────────
    async def _broadcast_event(self, session: UserSession, event_type: str):
        if self.ws_manager is None:
            return
        sat = session.current_satellite
        frame = TelemetryFrame(
            user_id=session.user_id,
            timestamp=time.time(),
            state=session.state.value,
            satellite_id=sat.id,
            gateway_name=session.gateway.name,
            elevation=sat.elevation,
            azimuth=sat.azimuth,
            cn_db=sat.cn_db,
            signal_quality=sat.signal_quality,
            slant_range_km=sat.slant_range_km,
            handover_count=session.handover_count,
            bytes_transferred=session.bytes_transferred,
            uptime_s=session.uptime_s,
            event_type=event_type,
        )
        await self.ws_manager.broadcast(frame.to_dict())

    # ── Handover execution (make-before-break) ───────────────────────────────
    async def _perform_handover(self, session: UserSession, reason: str) -> bool:
        old_sat = session.current_satellite
        old_gw = session.gateway
        t_start = time.time()

        session.state = SessionState.HANDOVER
        self._log("HANDOVER", session.user_id,
                  f"Bắt đầu HO | {old_sat.id} elev={old_sat.elevation:.1f}° C/N={old_sat.cn_db:.1f}dB | reason={reason}")
        await self._broadcast_event(session, "HANDOVER_START")

        # Pre-establish & switch (simulate)
        await asyncio.sleep(self.cfg.pre_establish_ms / 1000)
        await asyncio.sleep(self.cfg.switch_time_ms / 1000)

        # At this point, we would normally select a new satellite.
        # For simplicity, we keep the same satellite (it will be updated by next telemetry).
        # However, if we had a list of candidate satellites, we could choose the best.
        latency_ms = (time.time() - t_start) * 1000

        # Create new satellite object (temporary, will be overwritten)
        new_sat = Satellite(
            id=old_sat.id,
            elevation=old_sat.elevation,
            azimuth=old_sat.azimuth,
            cn_db=old_sat.cn_db,
            slant_range_km=old_sat.slant_range_km,
            serving_gateway=session.gateway.name,
        )
        # Record handover (gateway remains old for now, will be updated)
        session.record_handover(old_sat, new_sat, session.gateway, latency_ms, HandoverType.INTRA_GATEWAY)
        session.current_satellite = new_sat

        await asyncio.sleep(self.cfg.release_time_ms / 1000)
        session.state = SessionState.CONNECTED

        old_gw.active_sessions = max(0, old_gw.active_sessions - 1)
        old_gw.total_handovers += 1

        self._log("HANDOVER", session.user_id,
                  f"HO hoàn tất, chờ telemetry mới | latency={latency_ms:.1f}ms")
        await self._broadcast_event(session, "HANDOVER_DONE")
        return True

    # ── Monitor loop (runs per session) ──────────────────────────────────────
    async def _monitor_session(self, session: UserSession):
        while session.state != SessionState.DISCONNECTED:
            sat = session.current_satellite

            # Update estimated throughput
            if session.state == SessionState.CONNECTED:
                throughput_mbps = max(0, sat.cn_db * 3)
                session.bytes_transferred += int(
                    throughput_mbps * 1e6 * self.cfg.monitor_interval_s / 8
                )

            # Check thresholds
            if session.state == SessionState.CONNECTED:
                needs_ho = False
                reason = ""

                if sat.elevation < self.cfg.elev_critical_deg:
                    needs_ho, reason = True, "elevation_critical"
                elif sat.cn_db < self.cfg.cn_critical_db:
                    needs_ho, reason = True, "cn_critical"
                elif sat.elevation < self.cfg.elev_warn_deg:
                    self._log("WARN", session.user_id,
                              f"Cảnh báo: elev={sat.elevation:.1f}° < {self.cfg.elev_warn_deg}°")
                elif sat.cn_db < self.cfg.cn_warn_db:
                    self._log("WARN", session.user_id,
                              f"Cảnh báo: C/N={sat.cn_db:.1f}dB < {self.cfg.cn_warn_db}dB")
                else:
                    self._log("INFO", session.user_id,
                              f"OK | elev={sat.elevation:.1f}° C/N={sat.cn_db:.1f}dB "
                              f"range={sat.slant_range_km:.0f}km GW={session.gateway.name}")

                if needs_ho:
                    success = await self._perform_handover(session, reason)
                    if not success:
                        session.state = SessionState.SEARCHING
                        await asyncio.sleep(3)

            # Disconnect if elevation too low
            if sat.elevation < self.cfg.elev_min_deg:
                session.state = SessionState.DISCONNECTED
                self._log("DISCONNECT", session.user_id,
                          "Phiên kết thúc — vệ tinh dưới đường chân trời")
                await self._broadcast_event(session, "DISCONNECTED")
                break

            await self._broadcast_event(session, "TELEMETRY")
            await asyncio.sleep(self.cfg.monitor_interval_s)

        self._monitor_tasks.pop(session.user_id, None)

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC API (dùng từ api.py)
    # ══════════════════════════════════════════════════════════════════════════

    async def add_session(self, user_id: str, user_lat: float = 0.0, user_lon: float = 0.0) -> UserSession:
        dummy_gw = Gateway(name="Unknown")
        sat = Satellite(id="PENDING", elevation=45.0, azimuth=180.0,
                        cn_db=10.0, slant_range_km=800.0, serving_gateway="Unknown")
        session = UserSession(
            user_id=user_id,
            current_satellite=sat,
            gateway=dummy_gw,
            user_lat=user_lat,
            user_lon=user_lon,
        )
        self.sessions[user_id] = session
        self._log("CONNECT", user_id, "Session tạo, chờ telemetry...")
        task = asyncio.create_task(self._monitor_session(session))
        self._monitor_tasks[user_id] = task
        return session

    def gateway_status(self) -> List[Dict]:
        """Tổng hợp từ các session đang hoạt động."""
        gw_map = {}
        for sess in self.sessions.values():
            gw = sess.gateway
            if gw.name not in gw_map:
                gw_map[gw.name] = {
                    "name": gw.name,
                    "status": gw.status,
                    "active_sessions": 0,
                    "total_handovers": 0,
                }
            gw_map[gw.name]["active_sessions"] += 1
            gw_map[gw.name]["total_handovers"] += sess.handover_count
        return list(gw_map.values())

    def session_summary(self) -> List[Dict]:
        return [s.summary() for s in self.sessions.values()]

    def print_report(self) -> None:
        print("\n" + "═" * 65)
        print("  VNU-LEO Handover Engine — Báo cáo")
        print("═" * 65)
        for s in self.sessions.values():
            print(f"\n  {s.user_id}:")
            print(f"    Gateway: {s.gateway.name}, Vệ tinh: {s.current_satellite.id}")
            print(f"    Số HO: {s.handover_count}, Trung bình latency: {s.avg_latency_ms:.1f}ms")
            print(f"    Data: {s.bytes_transferred/1e6:.1f} MB, Uptime: {s.uptime_s:.0f}s")
        print("\n  Trạng thái Gateway:")
        for gw in self.gateway_status():
            print(f"    {gw['name']:12s}  sessions={gw['active_sessions']}  total_HO={gw['total_handovers']}")
        print("═" * 65)