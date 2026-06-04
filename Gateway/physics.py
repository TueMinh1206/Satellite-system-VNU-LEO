"""
core/physics.py
───────────────
Các công thức vật lý và thuật toán lõi của Tầng 2 VNU-LEO.

Gồm:
  - SGP4Simulator  : mô phỏng quỹ đạo vệ tinh (thay thế sgp4 thật)
  - LinkBudget     : tính C/N theo Friis + ITU-R P.618 rain fade
  - haversine()    : khoảng cách trên mặt cầu (chọn Gateway)
  - slant_range()  : khoảng cách xiên vệ tinh-gateway
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Tuple


# ── Hằng số ───────────────────────────────────────────────────────────────────

R_E      = 6371.0    # km — bán kính Trái Đất
MU       = 3.986e5   # km³/s² — hằng số hấp dẫn
C        = 3e8       # m/s — tốc độ ánh sáng
K_BOLTZ  = 1.38e-23  # J/K — hằng số Boltzmann

# Thông số hệ thống VNU-LEO
ALTITUDE_KM   = 550.0    # km — độ cao quỹ đạo (như Starlink)
INCLINATION   = 53.0     # độ — góc nghiêng Walker Delta
FREQ_GHZ      = 12.5     # GHz — Ku-band downlink
EIRP_DBW      = 45.0     # dBW — công suất phát vệ tinh
GT_DB_K       = 15.0     # dB/K — Figure of Merit ăng-ten mặt đất
BANDWIDTH_MHZ = 250.0    # MHz — băng thông kênh


# ── Haversine ─────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float,
              lat2: float, lon2: float) -> float:
    """
    Tính khoảng cách đại viên (Great Circle) trên mặt cầu giữa 2 điểm.

    Công thức Haversine:
        a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2)
        c = 2·arcsin(√a)
        d = R_E · c

    Args:
        lat1, lon1: tọa độ điểm 1 (độ)
        lat2, lon2: tọa độ điểm 2 (độ)

    Returns:
        Khoảng cách (km)
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R_E * math.asin(math.sqrt(a))


# ── Slant range ───────────────────────────────────────────────────────────────

def slant_range(altitude_km: float, elevation_deg: float) -> float:
    """
    Khoảng cách xiên (slant range) từ gateway đến vệ tinh.

    Dùng định lý sin trên tam giác cầu:
        d = R_E · sin(ρ) / cos(ε + ρ)
    với ρ là half-angle phủ sóng.

    Args:
        altitude_km:   độ cao quỹ đạo (km)
        elevation_deg: góc ngẩng (độ)

    Returns:
        Slant range (km)
    """
    eps = math.radians(elevation_deg)
    rho = math.acos(R_E / (R_E + altitude_km) * math.cos(eps)) - eps
    return R_E * math.sin(rho) / math.cos(eps + rho)


# ── Link Budget ───────────────────────────────────────────────────────────────

class LinkBudget:
    """
    Tính Link Budget theo phương trình Friis + ITU-R P.618.

    Phương trình Friis tổng quát:
        C/N (dB) = EIRP - FSPL - L_atm - L_rain + G/T - k - B

    Trong đó:
        FSPL = 20·log10(d) + 20·log10(f) + 92.45   (d km, f GHz)
        k    = 10·log10(K_BOLTZMANN) = -228.6 dBW/K/Hz
        B    = 10·log10(bandwidth_hz)
    """

    @staticmethod
    def free_space_path_loss(slant_km: float, freq_ghz: float) -> float:
        """
        Free Space Path Loss (FSPL) theo Friis.

        FSPL (dB) = 20·log10(d_km) + 20·log10(f_GHz) + 92.45
        """
        return 20 * math.log10(slant_km) + 20 * math.log10(freq_ghz) + 92.45

    @staticmethod
    def atmospheric_loss(elevation_deg: float) -> float:
        """
        Suy hao khí quyển (troposphere + ionosphere).
        Xấp xỉ: giảm khi elevation tăng (đường truyền ngắn hơn qua khí quyển).

        Mô hình đơn giản hóa cho Ku-band:
            L_atm ≈ 0.3 / sin(ε) + 0.1  (dB)
        """
        eps = math.radians(max(elevation_deg, 5.0))
        return 0.3 / math.sin(eps) + 0.1

    @staticmethod
    def rain_fade_itu(elevation_deg: float,
                      freq_ghz: float,
                      rain_rate_mm_hr: float = 50.0,
                      lat: float = 16.0) -> float:
        """
        Suy hao mưa theo mô hình ITU-R P.618-13.

        Việt Nam có lượng mưa cao (Rain Zone N/P), rain_rate_mm_hr ≈ 50-100 mm/hr.

        Các bước tính:
        1. Chiều cao mưa: h_rain = 5 - 0.075·(lat - 23) km
        2. Path length:   L_s = h_rain / sin(ε) km
        3. Specific attenuation: γ_r = k · R^α  (dB/km)
           k, α lấy từ bảng ITU-R P.838 theo tần số
        4. Reduction factor: r = 1 / (1 + L_s/35)
        5. Rain attenuation: A = γ_r · L_s · r  (dB)
        """
        # Coefficients ITU-R P.838-3 cho Ku-band (~12.5 GHz), linear polarization
        if freq_ghz < 8:
            k_coeff, alpha = 0.00454, 1.327
        elif freq_ghz < 15:
            k_coeff, alpha = 0.0167, 1.230
        else:
            k_coeff, alpha = 0.0335, 1.128

        # Chiều cao mưa (km)
        h_rain = max(0.5, 5.0 - 0.075 * (lat - 23))
        eps    = math.radians(max(elevation_deg, 5.0))

        # Path length qua lớp mưa
        L_s = h_rain / math.sin(eps)

        # Specific attenuation (dB/km)
        gamma_r = k_coeff * (rain_rate_mm_hr ** alpha)

        # Reduction factor (ITU-R P.618 §2.2.1.1)
        r = 1.0 / (1.0 + L_s / 35.0)

        return gamma_r * L_s * r

    @classmethod
    def compute_cn(cls,
                   elevation_deg: float,
                   altitude_km: float    = ALTITUDE_KM,
                   freq_ghz: float       = FREQ_GHZ,
                   eirp_dbw: float       = EIRP_DBW,
                   gt_db_k: float        = GT_DB_K,
                   bw_mhz: float         = BANDWIDTH_MHZ,
                   rain_rate_mm_hr: float = 0.0) -> float:
        """
        Tính C/N tổng hợp theo Friis + rain fade.

        Returns:
            C/N (dB) — âm nghĩa link không đạt yêu cầu
        """
        if elevation_deg <= 0:
            return -999.0

        d_km   = slant_range(altitude_km, elevation_deg)
        fspl   = cls.free_space_path_loss(d_km, freq_ghz)
        l_atm  = cls.atmospheric_loss(elevation_deg)
        l_rain = cls.rain_fade_itu(elevation_deg, freq_ghz, rain_rate_mm_hr)

        k_db   = -228.6                                  # dBW/K/Hz
        b_db   = 10 * math.log10(bw_mhz * 1e6)          # dB·Hz

        cn = eirp_dbw - fspl - l_atm - l_rain + gt_db_k - k_db - b_db
        return cn


# ── SGP4 Simulator ────────────────────────────────────────────────────────────

class SGP4Simulator:
    """
    Mô phỏng quỹ đạo vệ tinh LEO (thay thế thư viện sgp4 thật).

    Trong dự án thực tế, dùng: from sgp4.api import Satrec, jday
    Ở đây dùng mô hình hình học đơn giản hóa để demo mà không cần
    cài thêm thư viện.

    Mô hình:
        - Vệ tinh chuyển động đều trên quỹ đạo tròn
        - Elevation thay đổi theo hàm sin của thời gian
        - Mỗi vệ tinh có phase offset ngẫu nhiên → pass khác nhau
    """

    # Chu kỳ quỹ đạo LEO 550 km ≈ 95.5 phút
    ORBITAL_PERIOD_S = 95.5 * 60

    def __init__(self, sat_id: str, orbital_plane: int = 0,
                 phase_offset_s: float = 0.0):
        self.sat_id         = sat_id
        self.orbital_plane  = orbital_plane
        self.phase_offset_s = phase_offset_s
        self._t0            = time.time()

    def _orbital_angle(self, t: float | None = None) -> float:
        """Góc quỹ đạo hiện tại (radian)."""
        if t is None:
            t = time.time()
        elapsed = (t - self._t0 + self.phase_offset_s) % self.ORBITAL_PERIOD_S
        return 2 * math.pi * elapsed / self.ORBITAL_PERIOD_S

    def elevation_at(self, gw_lat: float, gw_lon: float,
                     t: float | None = None) -> float:
        """
        Tính elevation của vệ tinh nhìn từ gateway tại thời điểm t.

        Mô hình đơn giản: elevation = 60·sin(θ + δ) + noise
        với δ là offset phụ thuộc vào vị trí gateway.
        """
        theta = self._orbital_angle(t)
        # Phase offset theo lat/lon gateway tạo ra các đường pass khác nhau
        delta = (gw_lat * 0.05 + gw_lon * 0.03 + self.orbital_plane * 0.8)
        elev  = 60.0 * math.sin(theta + delta)
        # Thêm nhiễu nhỏ (±1°) mô phỏng sai số quỹ đạo thực
        elev += random.gauss(0, 0.8)
        return elev

    def azimuth_at(self, gw_lat: float, gw_lon: float,
                   t: float | None = None) -> float:
        """Tính azimuth (phương vị) của vệ tinh."""
        theta = self._orbital_angle(t)
        az    = (math.degrees(theta) + gw_lon) % 360
        return az

    def predict_elevation(self, gw_lat: float, gw_lon: float,
                           ahead_s: float = 60.0) -> float:
        """Dự đoán elevation sau `ahead_s` giây (phục vụ Predictive HO)."""
        return self.elevation_at(gw_lat, gw_lon, t=time.time() + ahead_s)

    def time_until_set(self, gw_lat: float, gw_lon: float,
                        min_elev: float = 5.0) -> float:
        """
        Ước tính số giây còn lại trước khi vệ tinh xuống dưới min_elev.
        Dùng binary search đơn giản.
        """
        t_now = time.time()
        lo, hi = 0.0, 600.0  # tìm trong 10 phút tới
        for _ in range(20):
            mid  = (lo + hi) / 2
            elev = self.elevation_at(gw_lat, gw_lon, t=t_now + mid)
            if elev < min_elev:
                hi = mid
            else:
                lo = mid
        return lo


# ── Constellation ─────────────────────────────────────────────────────────────

class WalkerConstellation:
    """
    Walker Delta Constellation cho VNU-LEO.

    Ký hiệu Walker: T/P/F
      T = tổng số vệ tinh
      P = số mặt phẳng quỹ đạo
      F = phasing factor (0 … P-1)

    Với 550 km, 53°: khuyến nghị 24/6/1 (4 vệ tinh/plane × 6 planes)
    hoặc tối thiểu 18/6/1 để đủ phủ Việt Nam liên tục.
    """

    def __init__(self, T: int = 24, P: int = 6, F: int = 1):
        self.T = T
        self.P = P
        self.F = F
        self.sats_per_plane = T // P

        # Tạo SGP4Simulator cho từng vệ tinh
        self.simulators: list[SGP4Simulator] = []
        period = SGP4Simulator.ORBITAL_PERIOD_S
        raan_step = period / P  # Khoảng cách thời gian giữa các plane

        sat_idx = 0
        for plane in range(P):
            for slot in range(self.sats_per_plane):
                phase = (plane * raan_step +
                         slot * period / self.sats_per_plane +
                         plane * F * period / T)
                sim = SGP4Simulator(
                    sat_id=f"VNU-{sat_idx + 1:02d}",
                    orbital_plane=plane,
                    phase_offset_s=phase % period,
                )
                self.simulators.append(sim)
                sat_idx += 1

    def visible_satellites(self, gw_lat: float, gw_lon: float,
                            min_elev: float = 15.0) -> list[dict]:
        """
        Trả về danh sách vệ tinh đang trong tầm nhìn của gateway.

        Args:
            gw_lat, gw_lon: tọa độ gateway
            min_elev: góc ngẩng tối thiểu (độ)

        Returns:
            List[dict] với keys: sat_id, elevation, azimuth, cn_db, slant_km, score
        """
        visible = []
        for sim in self.simulators:
            elev = sim.elevation_at(gw_lat, gw_lon)
            if elev < min_elev:
                continue
            az     = sim.azimuth_at(gw_lat, gw_lon)
            sr_km  = slant_range(ALTITUDE_KM, elev)
            cn     = LinkBudget.compute_cn(elev)
            # Weighted score: α=0.4 elevation, β=0.6 C/N  (tunable)
            score  = 0.4 * elev + 0.6 * cn
            visible.append({
                "sat_id":    sim.sat_id,
                "elevation": round(elev, 2),
                "azimuth":   round(az, 1),
                "cn_db":     round(cn, 2),
                "slant_km":  round(sr_km, 1),
                "score":     round(score, 3),
                "sim":       sim,
            })
        return sorted(visible, key=lambda x: x["score"], reverse=True)

    def best_satellite(self, gw_lat: float, gw_lon: float,
                        min_elev: float = 15.0) -> dict | None:
        """Trả về vệ tinh có score cao nhất, hoặc None nếu không có."""
        vis = self.visible_satellites(gw_lat, gw_lon, min_elev)
        return vis[0] if vis else None
