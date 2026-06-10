"""
entities.py
──────────────────
Các kiểu dữ liệu cốt lõi của hệ thống VNU-LEO Tầng 2.

Gồm: Gateway, Satellite, UserSession, SessionState, HandoverEvent
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class SessionState(Enum):
    """Trạng thái của một phiên kết nối người dùng."""
    CONNECTED    = "CONNECTED"     # Đang kết nối bình thường
    HANDOVER     = "HANDOVER"      # Đang thực hiện chuyển giao vệ tinh
    SEARCHING    = "SEARCHING"     # Không tìm thấy vệ tinh phù hợp
    DISCONNECTED = "DISCONNECTED"  # Phiên kết thúc


class HandoverType(Enum):
    """Loại handover xảy ra."""
    INTRA_GATEWAY = "INTRA_GATEWAY"  # Cùng gateway, đổi vệ tinh
    INTER_GATEWAY = "INTER_GATEWAY"  # Đổi cả gateway lẫn vệ tinh
    FORCED        = "FORCED"         # Bắt buộc vì C/N quá thấp


# ── Gateway ───────────────────────────────────────────────────────────────────

@dataclass
class Gateway:
    """
    Trạm mặt đất (Ground Station).

    Tọa độ 3 gateway VNU-LEO:
      - Hà Nội:  21.03°N, 105.85°E  (phục vụ miền Bắc)
      - Đà Nẵng: 16.07°N, 108.22°E  (phục vụ miền Trung)
      - TP.HCM:  10.82°N, 106.63°E  (phục vụ miền Nam)
    """
    name: str
    lat: float               # Vĩ độ (độ Bắc)
    lon: float               # Kinh độ (độ Đông)
    active_sessions: int = 0
    total_handovers: int = 0
    status: str = "ALIVE"    # ALIVE | DEGRADED | DEAD
    max_sessions: int = 1000

    @property
    def is_available(self) -> bool:
        return self.status == "ALIVE" and self.active_sessions < self.max_sessions

    def __str__(self) -> str:
        return f"GW[{self.name}] sessions={self.active_sessions} status={self.status}"


# ── Satellite ─────────────────────────────────────────────────────────────────

@dataclass
class Satellite:
    """
    Vệ tinh LEO (Low Earth Orbit).

    Thông số quan trọng:
      - elevation: góc ngẩng so với đường chân trời (độ). Handover khi < 25°.
      - azimuth:   phương vị (0°=Bắc, 90°=Đông, 180°=Nam, 270°=Tây)
      - cn_db:     tỷ số C/N (Carrier-to-Noise) tính bằng dB.
                   Chất lượng tốt khi > 10 dB; handover khi < 5 dB.
      - slant_range_km: khoảng cách xiên vệ tinh-gateway (km)
    """
    id: str
    elevation: float          # độ, [0, 90]
    azimuth: float            # độ, [0, 360)
    cn_db: float              # dB
    slant_range_km: float = 0.0
    serving_gateway: Optional[str] = None
    orbital_plane: int = 0    # Chỉ số mặt phẳng quỹ đạo (Walker)

    @property
    def signal_quality(self) -> str:
        """Phân loại chất lượng tín hiệu."""
        if self.cn_db >= 15:
            return "EXCELLENT"
        elif self.cn_db >= 10:
            return "GOOD"
        elif self.cn_db >= 5:
            return "FAIR"
        return "POOR"

    def __str__(self) -> str:
        return (f"SAT[{self.id}] elev={self.elevation:.1f}° "
                f"az={self.azimuth:.0f}° C/N={self.cn_db:.1f}dB "
                f"({self.signal_quality})")


# ── Session ───────────────────────────────────────────────────────────────────

@dataclass
class UserSession:
    """
    Phiên kết nối của một người dùng.

    Duy trì trạng thái toàn bộ vòng đời kết nối:
    từ lúc kết nối → các lần handover → đến khi phiên kết thúc.
    """
    user_id: str
    current_satellite: Satellite
    gateway: Gateway
    user_lat: float = 16.0    # Vị trí người dùng (mặc định Đà Nẵng)
    user_lon: float = 108.0

    # Trạng thái
    state: SessionState = SessionState.CONNECTED
    start_time: float = field(default_factory=time.time)

    # Thống kê
    handover_count: int = 0
    handover_history: list = field(default_factory=list)
    bytes_transferred: int = 0
    total_latency_ms: float = 0.0
    dropped_packets: int = 0

    @property
    def uptime_s(self) -> float:
        return time.time() - self.start_time

    @property
    def avg_latency_ms(self) -> float:
        if self.handover_count == 0:
            return 0.0
        return self.total_latency_ms / self.handover_count

    def record_handover(self, old_sat: Satellite, new_sat: Satellite,
                        new_gw: Gateway, latency_ms: float,
                        ho_type: HandoverType) -> None:
        """Ghi lại lịch sử một lần handover."""
        self.handover_count += 1
        self.total_latency_ms += latency_ms
        self.handover_history.append({
            "n":          self.handover_count,
            "time":       time.strftime("%H:%M:%S"),
            "from_sat":   old_sat.id,
            "to_sat":     new_sat.id,
            "from_gw":    self.gateway.name,
            "to_gw":      new_gw.name,
            "latency_ms": round(latency_ms, 1),
            "type":       ho_type.value,
        })

    def summary(self) -> dict:
        return {
            "user_id":       self.user_id,
            "state":         self.state.value,
            "uptime_s":      round(self.uptime_s, 1),
            "gateway":       self.gateway.name,
            "satellite":     self.current_satellite.id,
            "elevation":     round(self.current_satellite.elevation, 1),
            "cn_db":         round(self.current_satellite.cn_db, 1),
            "handover_count": self.handover_count,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "data_MB":       round(self.bytes_transferred / 1e6, 2),
        }


# ── Event (để broadcast qua WebSocket) ───────────────────────────────────────

@dataclass
class TelemetryFrame:
    """
    Frame dữ liệu real-time được gửi qua WebSocket mỗi 1 giây.
    Đây là cấu trúc JSON được SvelteKit dashboard nhận và hiển thị.
    """
    user_id: str
    timestamp: float
    state: str
    satellite_id: str
    gateway_name: str
    elevation: float
    azimuth: float
    cn_db: float
    signal_quality: str
    slant_range_km: float
    handover_count: int
    bytes_transferred: int
    uptime_s: float
    event_type: str = "TELEMETRY"   # TELEMETRY | HANDOVER_START | HANDOVER_DONE | WARN | ERROR

    def to_dict(self) -> dict:
        return {
            "user_id":          self.user_id,
            "timestamp":        self.timestamp,
            "state":            self.state,
            "satellite_id":     self.satellite_id,
            "gateway_name":     self.gateway_name,
            "elevation":        round(self.elevation, 2),
            "azimuth":          round(self.azimuth, 1),
            "cn_db":            round(self.cn_db, 2),
            "signal_quality":   self.signal_quality,
            "slant_range_km":   round(self.slant_range_km, 1),
            "handover_count":   self.handover_count,
            "bytes_transferred": self.bytes_transferred,
            "uptime_s":         round(self.uptime_s, 1),
            "event_type":       self.event_type,
        }
