"""
handover_engine.py
───────────────────────
Engine chính của Tầng 2 VNU-LEO.

Gồm:
  - HandoverConfig   : cấu hình ngưỡng và tham số
  - ConnectionManager: quản lý danh sách WebSocket clients
  - HandoverEngine   : vòng lặp giám sát + thực hiện handover
  - run_simulation() : entry point chạy mô phỏng độc lập (không cần FastAPI)
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Coroutine

from .physics import (
    ALTITUDE_KM, LinkBudget, WalkerConstellation,
    haversine, slant_range,
)
from .entities import (
    Gateway, HandoverType, Satellite,
    SessionState, TelemetryFrame, UserSession,
)


# ── Cấu hình hệ thống ─────────────────────────────────────────────────────────

@dataclass
class HandoverConfig:
    """
    Toàn bộ tham số có thể điều chỉnh của Handover Engine.
    Thay đổi ở đây ảnh hưởng toàn bộ hệ thống — không hardcode trong logic.
    """
    # Ngưỡng elevation
    elev_warn_deg:     float = 25.0   # Bắt đầu cảnh báo và tìm ứng viên
    elev_critical_deg: float = 15.0   # Bắt buộc handover ngay
    elev_min_deg:      float = 5.0    # Dưới mức này → không thể kết nối

    # Ngưỡng tín hiệu
    cn_warn_db:        float = 8.0    # Cảnh báo C/N thấp
    cn_critical_db:    float = 5.0    # Bắt buộc handover vì C/N

    # Predictive handover
    prediction_horizon_s: float = 60.0   # Dự đoán trước 60 giây
    pre_establish_ms:     float = 30.0   # Thời gian chuẩn bị link mới

    # Timing
    monitor_interval_s:   float = 1.0    # Chu kỳ vòng lặp giám sát
    switch_time_ms:       float = 20.0   # Thời gian atomic switch
    release_time_ms:      float = 10.0   # Thời gian giải phóng link cũ

    # Weighted score cho Best Satellite Selection
    alpha_elevation: float = 0.4   # Trọng số elevation
    beta_cn:         float = 0.6   # Trọng số C/N ratio

    @property
    def total_ho_time_ms(self) -> float:
        return self.pre_establish_ms + self.switch_time_ms + self.release_time_ms


# ── Gateway registry ──────────────────────────────────────────────────────────

# 3 Gateway VNU-LEO theo đề bài
GATEWAYS: list[Gateway] = [
    Gateway(name="Hà Nội",  lat=21.03, lon=105.85),
    Gateway(name="Đà Nẵng", lat=16.07, lon=108.22),
    Gateway(name="TP.HCM",  lat=10.82, lon=106.63),
]


def select_gateway(user_lat: float, user_lon: float) -> Gateway:
    """
    Chọn gateway phục vụ dựa trên khoảng cách Haversine đến người dùng.
    Gateway nào gần nhất → được chọn (giảm latency feeder link).
    """
    return min(
        GATEWAYS,
        key=lambda gw: haversine(user_lat, user_lon, gw.lat, gw.lon)
    )


# ── WebSocket Connection Manager ──────────────────────────────────────────────

class ConnectionManager:
    """
    Quản lý danh sách WebSocket clients đang kết nối.
    Được FastAPI inject vào HandoverEngine để broadcast real-time.
    """

    def __init__(self):
        # Set của các WebSocket objects (FastAPI WebSocket)
        self._clients: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, data: dict) -> None:
        """Gửi JSON tới tất cả clients đang kết nối. Bỏ qua client lỗi."""
        msg = json.dumps(data, ensure_ascii=False)
        dead = set()
        async with self._lock:
            clients = set(self._clients)

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


# ── Handover Engine ───────────────────────────────────────────────────────────

class HandoverEngine:
    """
    Engine chính điều phối toàn bộ Tầng 2:
      1. Monitor loop: giám sát elevation + C/N mỗi giây
      2. Predictive HO: dự đoán 60s tới, chuẩn bị sẵn ứng viên
      3. Best Sat Selection: weighted score α·elev + β·C/N
      4. Make-before-break: thiết lập link mới TRƯỚC khi cắt link cũ
      5. Broadcast: push TelemetryFrame qua WebSocket → SvelteKit dashboard
    """

    def __init__(self,
                 config: HandoverConfig | None = None,
                 ws_manager: ConnectionManager | None = None):
        self.cfg        = config or HandoverConfig()
        self.ws_manager = ws_manager
        self.sessions:  dict[str, UserSession] = {}
        self.event_log: list[dict] = []
        self._constellation = WalkerConstellation(T=24, P=6, F=1)
        self._running = False

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, level: str, user_id: str, msg: str) -> dict:
        icons = {
            "INFO":     "ℹ️ ",
            "WARN":     "⚠️ ",
            "HANDOVER": "🔄",
            "ERROR":    "❌",
            "CONNECT":  "🟢",
            "DISCONNECT":"🔴",
        }
        entry = {
            "time":    time.strftime("%H:%M:%S"),
            "level":   level,
            "user_id": user_id,
            "msg":     msg,
        }
        self.event_log.append(entry)
        icon = icons.get(level, "•")
        print(f"{icon} [{entry['time']}] [{user_id}] {msg}")
        return entry

    # ── Satellite selection ───────────────────────────────────────────────────

    def _weighted_score(self, elev: float, cn: float) -> float:
        """
        Weighted score để chọn vệ tinh tốt nhất.
        score = α·elev + β·C/N   (α + β = 1.0)
        """
        return self.cfg.alpha_elevation * elev + self.cfg.beta_cn * cn

    def _find_best_satellite(self, gw: Gateway) -> dict | None:
        """
        Tìm vệ tinh tốt nhất trong tầm nhìn của gateway.
        Dùng WalkerConstellation để liệt kê tất cả vệ tinh visible,
        rồi chọn theo weighted score.
        """
        return self._constellation.best_satellite(
            gw.lat, gw.lon, min_elev=self.cfg.elev_critical_deg
        )

    def _predict_needs_handover(self, session: UserSession) -> bool:
        """
        Predictive Handover: kiểm tra elevation 60s tới.
        Nếu sẽ dưới elev_warn → chuẩn bị handover sớm.
        """
        for sim in self._constellation.simulators:
            if sim.sat_id == session.current_satellite.id:
                future_elev = sim.predict_elevation(
                    session.gateway.lat,
                    session.gateway.lon,
                    ahead_s=self.cfg.prediction_horizon_s,
                )
                return future_elev < self.cfg.elev_warn_deg
        return False

    # ── Handover thực thi ─────────────────────────────────────────────────────

    async def _perform_handover(self, session: UserSession,
                                 reason: str = "elevation_low") -> bool:
        """
        Thực hiện Make-Before-Break Handover.

        Quy trình:
          1. Đánh dấu state = HANDOVER
          2. Tìm vệ tinh mới tốt nhất (có thể từ gateway khác)
          3. Pre-establish link mới (30ms)
          4. Atomic switch (20ms) — không mất gói tin
          5. Release link cũ (10ms)
          6. Cập nhật thống kê + broadcast event

        Returns:
            True nếu handover thành công, False nếu không tìm được vệ tinh
        """
        old_sat = session.current_satellite
        old_gw  = session.gateway
        t_start = time.time()

        # Bước 1: Chuyển trạng thái
        session.state = SessionState.HANDOVER
        self._log("HANDOVER", session.user_id,
                  f"Bắt đầu HO | {old_sat.id} elev={old_sat.elevation:.1f}° "
                  f"C/N={old_sat.cn_db:.1f}dB | reason={reason}")

        await self._broadcast_event(session, "HANDOVER_START")

        # Bước 2: Chọn gateway tốt nhất cho user (có thể đổi GW)
        new_gw = select_gateway(session.user_lat, session.user_lon)

        # Bước 3: Tìm vệ tinh mới
        best = self._find_best_satellite(new_gw)
        if best is None:
            # Không tìm được → thử gateway khác
            for gw in GATEWAYS:
                if gw.name != new_gw.name:
                    best = self._find_best_satellite(gw)
                    if best:
                        new_gw = gw
                        break

        if best is None:
            session.state = SessionState.SEARCHING
            self._log("ERROR", session.user_id, "Không tìm được vệ tinh thay thế!")
            return False

        # Bước 4: Pre-establish link mới (make-before-break)
        await asyncio.sleep(self.cfg.pre_establish_ms / 1000)

        # Bước 5: Atomic switch
        new_sat = Satellite(
            id=best["sat_id"],
            elevation=best["elevation"],
            azimuth=best["azimuth"],
            cn_db=best["cn_db"],
            slant_range_km=best["slant_km"],
            serving_gateway=new_gw.name,
        )
        await asyncio.sleep(self.cfg.switch_time_ms / 1000)

        # Bước 6: Xác định loại HO
        ho_type = (HandoverType.INTRA_GATEWAY
                   if new_gw.name == old_gw.name
                   else HandoverType.INTER_GATEWAY)

        # Cập nhật session
        latency_ms = (time.time() - t_start) * 1000
        session.record_handover(old_sat, new_sat, new_gw, latency_ms, ho_type)
        session.current_satellite = new_sat
        session.gateway = new_gw

        # Release link cũ
        await asyncio.sleep(self.cfg.release_time_ms / 1000)
        session.state = SessionState.CONNECTED

        # Cập nhật counter gateway
        old_gw.active_sessions  = max(0, old_gw.active_sessions - 1)
        old_gw.total_handovers += 1
        new_gw.active_sessions += 1

        self._log("HANDOVER", session.user_id,
                  f"HO hoàn tất ({ho_type.value}) → {new_sat.id} "
                  f"elev={new_sat.elevation:.1f}° C/N={new_sat.cn_db:.1f}dB "
                  f"via GW {new_gw.name} | latency={latency_ms:.1f}ms")

        await self._broadcast_event(session, "HANDOVER_DONE")
        return True

    # ── Monitor loop ──────────────────────────────────────────────────────────

    async def _monitor_session(self, session: UserSession) -> None:
        """
        Vòng lặp giám sát 1 phiên kết nối.
        Chạy mỗi `monitor_interval_s` giây, kiểm tra:
          - Elevation + C/N hiện tại
          - Predictive HO (60s tới)
          - Kích hoạt handover nếu cần
        """
        while session.state != SessionState.DISCONNECTED:
            sat = session.current_satellite
            gw  = session.gateway

            # Cập nhật elevation + C/N từ SGP4 simulator
            for sim in self._constellation.simulators:
                if sim.sat_id == sat.id:
                    sat.elevation = sim.elevation_at(gw.lat, gw.lon)
                    sat.azimuth   = sim.azimuth_at(gw.lat, gw.lon)
                    sat.cn_db     = LinkBudget.compute_cn(
                        sat.elevation,
                        rain_rate_mm_hr=random.uniform(0, 30),   # mô phỏng mưa
                    )
                    sat.slant_range_km = slant_range(ALTITUDE_KM, max(sat.elevation, 1))
                    break

            # Giả lập data transfer
            if session.state == SessionState.CONNECTED:
                throughput_mbps = max(0, sat.cn_db * 3)  # C/N → throughput thô
                session.bytes_transferred += int(throughput_mbps * 1e6 *
                                                 self.cfg.monitor_interval_s / 8)

            # Kiểm tra ngưỡng và kích hoạt HO
            if session.state == SessionState.CONNECTED:
                needs_ho = False
                reason   = ""

                if sat.elevation < self.cfg.elev_critical_deg:
                    needs_ho, reason = True, "elevation_critical"
                elif sat.cn_db < self.cfg.cn_critical_db:
                    needs_ho, reason = True, "cn_critical"
                elif self._predict_needs_handover(session):
                    needs_ho, reason = True, "predictive"
                elif sat.elevation < self.cfg.elev_warn_deg:
                    self._log("WARN", session.user_id,
                              f"Cảnh báo: elev={sat.elevation:.1f}° < {self.cfg.elev_warn_deg}°")
                elif sat.cn_db < self.cfg.cn_warn_db:
                    self._log("WARN", session.user_id,
                              f"Cảnh báo: C/N={sat.cn_db:.1f}dB < {self.cfg.cn_warn_db}dB")
                else:
                    self._log("INFO", session.user_id,
                              f"OK | elev={sat.elevation:.1f}° C/N={sat.cn_db:.1f}dB "
                              f"slant={sat.slant_range_km:.0f}km "
                              f"data={session.bytes_transferred/1e6:.1f}MB")

                if needs_ho:
                    success = await self._perform_handover(session, reason)
                    if not success and session.state == SessionState.SEARCHING:
                        await asyncio.sleep(3)  # chờ 3s rồi thử lại

            # Kiểm tra phiên kết thúc
            if sat.elevation < self.cfg.elev_min_deg:
                session.state = SessionState.DISCONNECTED
                self._log("DISCONNECT", session.user_id,
                          "Phiên kết thúc — vệ tinh dưới đường chân trời")
                break

            # Push telemetry frame qua WebSocket
            await self._broadcast_event(session, "TELEMETRY")
            await asyncio.sleep(self.cfg.monitor_interval_s)

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def _broadcast_event(self, session: UserSession,
                                event_type: str) -> None:
        """Đóng gói TelemetryFrame và push cho tất cả WebSocket clients."""
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

    # ── Public API ────────────────────────────────────────────────────────────

    async def add_session(self, user_id: str,
                           user_lat: float, user_lon: float) -> UserSession:
        """Tạo phiên kết nối mới và bắt đầu giám sát."""
        gw   = select_gateway(user_lat, user_lon)
        best = self._find_best_satellite(gw)

        if best is None:
            raise RuntimeError(f"Không có vệ tinh phù hợp tại ({user_lat}, {user_lon})")

        sat = Satellite(
            id=best["sat_id"],
            elevation=best["elevation"],
            azimuth=best["azimuth"],
            cn_db=best["cn_db"],
            slant_range_km=best["slant_km"],
            serving_gateway=gw.name,
        )
        session = UserSession(
            user_id=user_id,
            current_satellite=sat,
            gateway=gw,
            user_lat=user_lat,
            user_lon=user_lon,
        )
        self.sessions[user_id] = session
        gw.active_sessions += 1

        self._log("CONNECT", user_id,
                  f"Kết nối qua GW {gw.name} → {sat.id} "
                  f"elev={sat.elevation:.1f}° C/N={sat.cn_db:.1f}dB")

        # Chạy monitor loop bất đồng bộ trong background
        asyncio.create_task(self._monitor_session(session))
        return session

    def gateway_status(self) -> list[dict]:
        """Trạng thái tất cả gateway — dùng cho Network Monitoring Dashboard."""
        return [
            {
                "name":             gw.name,
                "lat":              gw.lat,
                "lon":              gw.lon,
                "status":           gw.status,
                "active_sessions":  gw.active_sessions,
                "total_handovers":  gw.total_handovers,
            }
            for gw in GATEWAYS
        ]

    def session_summary(self) -> list[dict]:
        """Tóm tắt tất cả phiên — dùng cho thống kê cuối mô phỏng."""
        return [s.summary() for s in self.sessions.values()]

    def print_report(self) -> None:
        """In báo cáo tổng kết ra console."""
        print("\n" + "═" * 65)
        print("  VNU-LEO Tầng 2 — Báo cáo mô phỏng")
        print("═" * 65)
        for s in self.sessions.values():
            ho_types = {}
            for h in s.handover_history:
                ho_types[h["type"]] = ho_types.get(h["type"], 0) + 1
            print(f"\n  {s.user_id}")
            print(f"    Gateway cuối:    {s.gateway.name}")
            print(f"    Vệ tinh cuối:    {s.current_satellite.id}")
            print(f"    Số HO:           {s.handover_count}")
            print(f"    HO theo loại:    {ho_types}")
            print(f"    Avg HO latency:  {s.avg_latency_ms:.1f} ms")
            print(f"    Data transfer:   {s.bytes_transferred/1e6:.1f} MB")
            print(f"    Uptime:          {s.uptime_s:.0f} s")
        print("\n  Trạng thái Gateway:")
        for gw in GATEWAYS:
            print(f"    {gw.name:12s}  sessions={gw.active_sessions}  "
                  f"total_HO={gw.total_handovers}  status={gw.status}")
        print("═" * 65)


# ── Standalone simulation (không cần FastAPI) ─────────────────────────────────

async def run_simulation(n_users: int = 3, duration_s: int = 30) -> None:
    """
    Chạy mô phỏng hoàn chỉnh không cần FastAPI.
    Dùng để test logic trước khi tích hợp với web server.

    Usage:
        python -m Gateway.core.handover_engine
    """
    print("\n" + "═" * 65)
    print("  VNU-LEO Tầng 2 — Gateway & Handover Simulator")
    print(f"  {n_users} users · {duration_s}s · Walker 24/6/1 · 550km")
    print("═" * 65 + "\n")

    engine = HandoverEngine()

    # Tạo users phân bố ngẫu nhiên trên lãnh thổ Việt Nam
    users = [
        ("User-HN-01", 21.03, 105.85),   # Hà Nội
        ("User-DN-01", 16.07, 108.22),   # Đà Nẵng
        ("User-HCM-01", 10.82, 106.63),  # TP.HCM
    ]
    for i in range(n_users - 3):
        lat = random.uniform(10.0, 23.0)
        lon = random.uniform(102.0, 110.0)
        users.append((f"User-{i+4:02d}", lat, lon))

    for user_id, lat, lon in users[:n_users]:
        await engine.add_session(user_id, lat, lon)

    try:
        await asyncio.sleep(duration_s)
    except asyncio.CancelledError:
        pass
    finally:
        engine.print_report()


if __name__ == "__main__":
    asyncio.run(run_simulation(n_users=3, duration_s=30))
