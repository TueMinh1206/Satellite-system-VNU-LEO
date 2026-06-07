"""
gui_dashboard.py
────────────────
VNU-LEO Tầng 2 — Giao diện đồ họa (tkinter)

Chạy:
    python gui_dashboard.py

Không cần cài thêm thư viện — chỉ dùng tkinter (có sẵn trong Python).
Engine chạy trong asyncio thread riêng, GUI cập nhật mỗi 1 giây qua queue.
"""

import asyncio
import math
import queue
import random
import threading
import time
import tkinter as tk
from tkinter import ttk, font as tkfont

# ── Nhúng thẳng physics + entities vào đây để chạy độc lập ──────────────────

R_E = 6371.0
MU  = 3.986e5
C   = 3e8
K_BOLTZ = 1.38e-23

ALTITUDE_KM   = 550.0
INCLINATION   = 53.0
FREQ_GHZ      = 12.5
EIRP_DBW      = 45.0
GT_DB_K       = 15.0
BANDWIDTH_MHZ = 250.0


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R_E * math.asin(math.sqrt(a))


def slant_range(altitude_km, elevation_deg):
    eps = math.radians(elevation_deg)
    rho = math.acos(R_E / (R_E + altitude_km) * math.cos(eps)) - eps
    return R_E * math.sin(rho) / math.cos(eps + rho)


class LinkBudget:
    @staticmethod
    def free_space_path_loss(slant_km, freq_ghz):
        return 20*math.log10(slant_km) + 20*math.log10(freq_ghz) + 92.45

    @staticmethod
    def atmospheric_loss(elevation_deg):
        eps = math.radians(max(elevation_deg, 5.0))
        return 0.3 / math.sin(eps) + 0.1

    @staticmethod
    def rain_fade(elevation_deg, freq_ghz, rain_rate=50.0, lat=16.0):
        k, alpha = 0.0167, 1.230
        h_rain = max(0.5, 5.0 - 0.075*(lat - 23))
        eps = math.radians(max(elevation_deg, 5.0))
        L_s = h_rain / math.sin(eps)
        gamma_r = k * (rain_rate ** alpha)
        r = 1.0 / (1.0 + L_s / 35.0)
        return gamma_r * L_s * r

    @classmethod
    def compute_cn(cls, elevation_deg, rain_rate=0.0):
        if elevation_deg <= 0:
            return -999.0
        d_km  = slant_range(ALTITUDE_KM, elevation_deg)
        fspl  = cls.free_space_path_loss(d_km, FREQ_GHZ)
        l_atm = cls.atmospheric_loss(elevation_deg)
        l_rain = cls.rain_fade(elevation_deg, FREQ_GHZ, rain_rate)
        k_db  = -228.6
        b_db  = 10 * math.log10(BANDWIDTH_MHZ * 1e6)
        return EIRP_DBW - fspl - l_atm - l_rain + GT_DB_K - k_db - b_db


class SGP4Simulator:
    ORBITAL_PERIOD_S = 95.5 * 60

    def __init__(self, sat_id, orbital_plane=0, phase_offset_s=0.0):
        self.sat_id = sat_id
        self.orbital_plane = orbital_plane
        self.phase_offset_s = phase_offset_s
        self._t0 = time.time()

    def _orbital_angle(self, t=None):
        if t is None: t = time.time()
        elapsed = (t - self._t0 + self.phase_offset_s) % self.ORBITAL_PERIOD_S
        return 2 * math.pi * elapsed / self.ORBITAL_PERIOD_S

    def elevation_at(self, gw_lat, gw_lon, t=None):
        theta = self._orbital_angle(t)
        delta = (gw_lat * 0.05 + gw_lon * 0.03 + self.orbital_plane * 0.8)
        elev  = 60.0 * math.sin(theta + delta) + random.gauss(0, 0.8)
        return elev

    def azimuth_at(self, gw_lat, gw_lon, t=None):
        theta = self._orbital_angle(t)
        return (math.degrees(theta) + gw_lon) % 360

    def predict_elevation(self, gw_lat, gw_lon, ahead_s=60.0):
        return self.elevation_at(gw_lat, gw_lon, t=time.time() + ahead_s)


class WalkerConstellation:
    def __init__(self, T=24, P=6, F=1):
        self.simulators = []
        period = SGP4Simulator.ORBITAL_PERIOD_S
        raan_step = period / P
        sat_idx = 0
        sats_per_plane = T // P
        for plane in range(P):
            for slot in range(sats_per_plane):
                phase = (plane * raan_step + slot * period / sats_per_plane
                         + plane * F * period / T)
                self.simulators.append(SGP4Simulator(
                    sat_id=f"VNU-{sat_idx+1:02d}",
                    orbital_plane=plane,
                    phase_offset_s=phase % period,
                ))
                sat_idx += 1

    def visible_satellites(self, gw_lat, gw_lon, min_elev=15.0):
        visible = []
        for sim in self.simulators:
            elev = sim.elevation_at(gw_lat, gw_lon)
            if elev < min_elev: continue
            az    = sim.azimuth_at(gw_lat, gw_lon)
            sr    = slant_range(ALTITUDE_KM, elev)
            cn    = LinkBudget.compute_cn(elev)
            score = 0.4*elev + 0.6*cn
            visible.append({"sat_id": sim.sat_id, "elevation": elev,
                             "azimuth": az, "cn_db": cn, "slant_km": sr,
                             "score": score, "sim": sim})
        return sorted(visible, key=lambda x: x["score"], reverse=True)

    def best_satellite(self, gw_lat, gw_lon, min_elev=15.0):
        vis = self.visible_satellites(gw_lat, gw_lon, min_elev)
        return vis[0] if vis else None


# ── Minimal Engine (standalone, không phụ thuộc file khác) ───────────────────

GATEWAYS_DATA = [
    {"name": "Hà Nội",  "lat": 21.03, "lon": 105.85},
    {"name": "Đà Nẵng", "lat": 16.07, "lon": 108.22},
    {"name": "TP.HCM",  "lat": 10.82, "lon": 106.63},
]


class SimpleEngine:
    """Engine đơn giản hóa chạy trong asyncio — push event vào queue."""

    def __init__(self, event_queue):
        self.q = event_queue
        self.constellation = WalkerConstellation(T=24, P=6, F=1)
        self.sessions = {}
        self.gateways = {gw["name"]: dict(gw, active=0, total_ho=0, status="ALIVE")
                         for gw in GATEWAYS_DATA}

    def _select_gateway(self, lat, lon):
        return min(GATEWAYS_DATA, key=lambda g: haversine(lat, lon, g["lat"], g["lon"]))

    def _find_best_sat(self, gw):
        return self.constellation.best_satellite(gw["lat"], gw["lon"], min_elev=15.0)

    async def add_session(self, user_id, lat, lon):
        gw   = self._select_gateway(lat, lon)
        best = self._find_best_sat(gw)
        if best is None:
            self._push_log("ERROR", user_id, "Không tìm được vệ tinh")
            return

        session = {
            "user_id":   user_id,
            "lat": lat, "lon": lon,
            "gateway":   gw["name"],
            "sat_id":    best["sat_id"],
            "sat_sim":   best["sim"],
            "elevation": best["elevation"],
            "azimuth":   best["azimuth"],
            "cn_db":     best["cn_db"],
            "slant_km":  best["slant_km"],
            "state":     "CONNECTED",
            "ho_count":  0,
            "data_bytes": 0,
            "uptime":    0,
            "start":     time.time(),
        }
        self.sessions[user_id] = session
        self.gateways[gw["name"]]["active"] += 1
        self._push_log("CONNECT", user_id,
                       f"Kết nối qua {gw['name']} → {best['sat_id']} "
                       f"elev={best['elevation']:.1f}° C/N={best['cn_db']:.1f}dB")
        asyncio.create_task(self._monitor(session))

    async def _monitor(self, s):
        while s["state"] != "DISCONNECTED":
            gw_data = next(g for g in GATEWAYS_DATA if g["name"] == s["gateway"])
            sim = s["sat_sim"]

            # Cập nhật telemetry
            elev  = sim.elevation_at(gw_data["lat"], gw_data["lon"])
            az    = sim.azimuth_at(gw_data["lat"], gw_data["lon"])
            rain  = random.uniform(0, 30)
            cn    = LinkBudget.compute_cn(elev, rain)
            sr    = slant_range(ALTITUDE_KM, max(elev, 1))

            s["elevation"] = elev
            s["azimuth"]   = az
            s["cn_db"]     = cn
            s["slant_km"]  = sr
            s["uptime"]    = time.time() - s["start"]

            if s["state"] == "CONNECTED":
                tp = max(0, cn * 3)
                s["data_bytes"] += int(tp * 1e6 / 8)

                # Ngưỡng kích hoạt HO
                needs_ho = False
                reason   = ""
                if elev < 15:
                    needs_ho, reason = True, "elevation_critical"
                elif cn < 5:
                    needs_ho, reason = True, "cn_critical"
                else:
                    future_elev = sim.predict_elevation(gw_data["lat"], gw_data["lon"], 60)
                    if future_elev < 25:
                        needs_ho, reason = True, "predictive"

                if elev < 25 and not needs_ho:
                    self._push_log("WARN", s["user_id"],
                                   f"Cảnh báo elev={elev:.1f}° C/N={cn:.1f}dB")

                if needs_ho:
                    await self._handover(s, reason)

            if elev < 5:
                s["state"] = "DISCONNECTED"
                self.gateways[s["gateway"]]["active"] = max(
                    0, self.gateways[s["gateway"]]["active"] - 1)
                self._push_log("DISCONNECT", s["user_id"], "Phiên kết thúc")

            # Push telemetry frame
            self.q.put(("TELEMETRY", dict(s)))
            await asyncio.sleep(1.0)

    async def _handover(self, s, reason):
        old_sat = s["sat_id"]
        old_gw  = s["gateway"]
        s["state"] = "HANDOVER"
        self._push_log("HANDOVER", s["user_id"],
                       f"HO bắt đầu ({reason}) từ {old_sat}")

        await asyncio.sleep(0.06)  # make-before-break ~60ms

        new_gw_data = self._select_gateway(s["lat"], s["lon"])
        best = self._find_best_sat(new_gw_data)
        if best is None:
            for gw in GATEWAYS_DATA:
                best = self._find_best_sat(gw)
                if best:
                    new_gw_data = gw
                    break

        if best is None:
            s["state"] = "SEARCHING"
            self._push_log("ERROR", s["user_id"], "Không tìm được vệ tinh thay thế")
            return

        # Cập nhật gateway counters
        self.gateways[old_gw]["total_ho"] += 1
        if new_gw_data["name"] != old_gw:
            self.gateways[old_gw]["active"] = max(0, self.gateways[old_gw]["active"] - 1)
            self.gateways[new_gw_data["name"]]["active"] += 1

        s["gateway"]  = new_gw_data["name"]
        s["sat_id"]   = best["sat_id"]
        s["sat_sim"]  = best["sim"]
        s["ho_count"] += 1
        s["state"]    = "CONNECTED"

        ho_type = "INTRA" if new_gw_data["name"] == old_gw else "INTER"
        self._push_log("HANDOVER", s["user_id"],
                       f"HO hoàn thành ({ho_type}) → {best['sat_id']} "
                       f"via {new_gw_data['name']}")

    def _push_log(self, level, user_id, msg):
        self.q.put(("LOG", {
            "time":    time.strftime("%H:%M:%S"),
            "level":   level,
            "user_id": user_id,
            "msg":     msg,
        }))
        icon = {"INFO":"ℹ", "WARN":"⚠", "HANDOVER":"↔",
                "ERROR":"✗", "CONNECT":"●", "DISCONNECT":"○"}.get(level, "•")
        print(f"{icon} [{time.strftime('%H:%M:%S')}] [{user_id}] {msg}")

    async def run(self, users):
        for uid, lat, lon in users:
            await self.add_session(uid, lat, lon)
        while True:
            self.q.put(("GATEWAYS", {n: dict(g) for n, g in self.gateways.items()}))
            await asyncio.sleep(2.0)


# ── Asyncio thread ────────────────────────────────────────────────────────────

def start_engine(event_queue, users):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    engine = SimpleEngine(event_queue)
    loop.run_until_complete(engine.run(users))


# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════

# ── Màu sắc ───────────────────────────────────────────────────────────────────
BG       = "#0d1117"
SURFACE  = "#161b22"
SURFACE2 = "#1c2230"
BORDER   = "#30363d"
TXT      = "#e6edf3"
MUTED    = "#8b949e"
HINT     = "#484f58"
GREEN    = "#1D9E75"
AMBER    = "#EF9F27"
RED      = "#E24B4A"
BLUE     = "#378ADD"
PURPLE   = "#7F77DD"
TEAL     = "#5DCAA5"

LEVEL_COLOR = {
    "INFO":       MUTED,
    "WARN":       AMBER,
    "HANDOVER":   BLUE,
    "ERROR":      RED,
    "CONNECT":    GREEN,
    "DISCONNECT": RED,
    "SYSTEM":     PURPLE,
}

SERIES_COLORS = [BLUE, GREEN, AMBER, RED, PURPLE, TEAL]


def cn_color(cn):
    if cn >= 15: return GREEN
    if cn >= 8:  return AMBER
    return RED

def elev_color(e):
    if e >= 30: return GREEN
    if e >= 15: return AMBER
    return RED

def fmt_bytes(b):
    if b < 1e3:  return f"{b} B"
    if b < 1e6:  return f"{b/1e3:.1f} KB"
    return f"{b/1e6:.1f} MB"


# ── Mini sparkline canvas ─────────────────────────────────────────────────────

class Sparkline(tk.Canvas):
    """Canvas nhỏ vẽ đường dữ liệu theo thời gian."""

    def __init__(self, parent, width=120, height=40, color=BLUE, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=SURFACE2, highlightthickness=0, **kw)
        self.w = width
        self.h = height
        self.color = color
        self.data = []

    def push(self, value):
        self.data.append(value)
        if len(self.data) > 40:
            self.data.pop(0)
        self._draw()

    def _draw(self):
        self.delete("all")
        if len(self.data) < 2:
            return
        lo = min(self.data)
        hi = max(self.data)
        rng = hi - lo or 1
        pts = []
        for i, v in enumerate(self.data):
            x = int(i / (len(self.data)-1) * self.w)
            y = int(self.h - (v - lo) / rng * (self.h - 4) - 2)
            pts.extend([x, y])
        self.create_line(*pts, fill=self.color, width=1.5, smooth=True)


# ── Carte phiên kết nối ───────────────────────────────────────────────────────

class SessionCard(tk.Frame):
    def __init__(self, parent, uid, color, **kw):
        super().__init__(parent, bg=SURFACE, padx=12, pady=10,
                         highlightthickness=1, highlightbackground=BORDER, **kw)
        self.uid   = uid
        self.color = color

        # Header
        hdr = tk.Frame(self, bg=SURFACE)
        hdr.pack(fill="x", pady=(0, 8))

        self.dot = tk.Label(hdr, text="●", fg=color, bg=SURFACE, font=("Segoe UI", 10))
        self.dot.pack(side="left")

        tk.Label(hdr, text=uid, fg=TXT, bg=SURFACE,
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=(4, 0))

        self.state_lbl = tk.Label(hdr, text="CONNECTED", fg=GREEN, bg=SURFACE,
                                  font=("Segoe UI", 9))
        self.state_lbl.pack(side="right")

        # Metrics grid
        metrics_frame = tk.Frame(self, bg=SURFACE)
        metrics_frame.pack(fill="x", pady=(0, 8))

        def metric_box(parent, label):
            f = tk.Frame(parent, bg=SURFACE2, padx=8, pady=6)
            tk.Label(f, text=label, fg=HINT, bg=SURFACE2,
                     font=("Segoe UI", 8)).pack(anchor="w")
            val = tk.Label(f, text="—", fg=TXT, bg=SURFACE2,
                           font=("Segoe UI", 14, "bold"))
            val.pack(anchor="w")
            return f, val

        for i in range(4):
            metrics_frame.columnconfigure(i, weight=1)

        self.cn_box,    self.cn_val    = metric_box(metrics_frame, "C/N (dB)")
        self.elev_box,  self.elev_val  = metric_box(metrics_frame, "Elevation")
        self.slant_box, self.slant_val = metric_box(metrics_frame, "Slant range")
        self.data_box,  self.data_val  = metric_box(metrics_frame, "Data")

        self.cn_box.grid(row=0, column=0, padx=(0,4), sticky="ew")
        self.elev_box.grid(row=0, column=1, padx=(0,4), sticky="ew")
        self.slant_box.grid(row=0, column=2, padx=(0,4), sticky="ew")
        self.data_box.grid(row=0, column=3, sticky="ew")

        # Elevation bar
        bar_frame = tk.Frame(self, bg=SURFACE)
        bar_frame.pack(fill="x", pady=(0, 6))
        tk.Label(bar_frame, text="Elevation", fg=HINT, bg=SURFACE,
                 font=("Segoe UI", 8)).pack(side="left")
        self.elev_pct_lbl = tk.Label(bar_frame, text="0° / 90°", fg=HINT, bg=SURFACE,
                                     font=("Segoe UI", 8))
        self.elev_pct_lbl.pack(side="right")

        self.bar_track = tk.Canvas(self, height=5, bg=SURFACE2, highlightthickness=0)
        self.bar_track.pack(fill="x", pady=(0, 8))
        self._bar_rect = self.bar_track.create_rectangle(0, 0, 0, 5, fill=GREEN, outline="")

        # Sparklines row
        spark_frame = tk.Frame(self, bg=SURFACE)
        spark_frame.pack(fill="x", pady=(0, 8))
        self.cn_spark   = Sparkline(spark_frame, color=self.color)
        self.elev_spark = Sparkline(spark_frame, color=TEAL)
        self.cn_spark.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.elev_spark.pack(side="left", fill="x", expand=True)

        # Footer
        foot = tk.Frame(self, bg=SURFACE, pady=4)
        foot.pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(0, 6))

        self.sat_lbl = tk.Label(foot, text="— → —", fg=MUTED, bg=SURFACE,
                                font=("Consolas", 9))
        self.sat_lbl.pack(side="left")
        self.ho_lbl  = tk.Label(foot, text="0 HO · 0s", fg=HINT, bg=SURFACE,
                                font=("Segoe UI", 9))
        self.ho_lbl.pack(side="right")

    def update_data(self, s):
        cn    = s.get("cn_db", 0)
        elev  = s.get("elevation", 0)
        state = s.get("state", "CONNECTED")

        # State + border
        state_colors = {"CONNECTED": GREEN, "HANDOVER": AMBER,
                        "SEARCHING": RED,   "DISCONNECTED": HINT}
        sc = state_colors.get(state, MUTED)
        self.state_lbl.config(text=state, fg=sc)
        self.config(highlightbackground=sc if state != "CONNECTED" else BORDER)

        # Metrics
        self.cn_val.config(text=f"{cn:.1f}", fg=cn_color(cn))
        self.elev_val.config(text=f"{elev:.1f}°", fg=elev_color(elev))
        self.slant_val.config(text=f"{s.get('slant_km', 0):.0f} km")
        self.data_val.config(text=fmt_bytes(s.get("data_bytes", 0)))

        # Elevation bar
        pct  = max(0, min(1, elev / 90))
        self.bar_track.update_idletasks()
        w = self.bar_track.winfo_width() or 200
        self.bar_track.coords(self._bar_rect, 0, 0, int(w * pct), 5)
        self.bar_track.itemconfig(self._bar_rect, fill=elev_color(elev))
        self.elev_pct_lbl.config(text=f"{elev:.1f}° / 90°")

        # Sparklines
        self.cn_spark.push(cn)
        self.elev_spark.push(max(0, elev))

        # Footer
        self.sat_lbl.config(text=f"{s.get('sat_id','—')} → {s.get('gateway','—')}")
        self.ho_lbl.config(text=f"{s.get('ho_count', 0)} HO · {s.get('uptime', 0):.0f}s")


# ── Main Dashboard Window ─────────────────────────────────────────────────────

class VNULeoDashboard(tk.Tk):

    def __init__(self, event_queue):
        super().__init__()
        self.q = event_queue
        self.session_cards = {}
        self.log_entries   = []

        self._setup_window()
        self._build_ui()
        self.after(500, self._poll_queue)

    def _setup_window(self):
        self.title("VNU-LEO Gateway & Handover Monitor")
        self.geometry("1200x820")
        self.minsize(900, 600)
        self.configure(bg=BG)

        # Style
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame",     background=BG)
        style.configure("TLabel",     background=BG, foreground=TXT)
        style.configure("TScrollbar", background=SURFACE2, troughcolor=BG,
                        arrowcolor=MUTED, bordercolor=BG)

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=SURFACE, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="VNU-LEO", fg=TEAL, bg=SURFACE,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=(16, 6), pady=12)
        tk.Label(hdr, text="Gateway & Handover Monitor", fg=TXT, bg=SURFACE,
                 font=("Segoe UI", 12)).pack(side="left", pady=12)

        self.status_lbl = tk.Label(hdr, text="● Đang chạy", fg=GREEN, bg=SURFACE,
                                   font=("Segoe UI", 10))
        self.status_lbl.pack(side="right", padx=16)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── Body (left + right) ───────────────────────────────────────────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=10)

        # LEFT: sessions + gateways
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        # Gateway row
        tk.Label(left, text="TRẠNG THÁI GATEWAY", fg=HINT, bg=BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        gw_row = tk.Frame(left, bg=BG)
        gw_row.pack(fill="x", pady=(0, 12))

        self.gw_cards = {}
        for gw in GATEWAYS_DATA:
            f = tk.Frame(gw_row, bg=SURFACE, padx=12, pady=8,
                         highlightthickness=1, highlightbackground=GREEN)
            f.pack(side="left", expand=True, fill="both", padx=(0, 6))

            hf = tk.Frame(f, bg=SURFACE)
            hf.pack(fill="x")
            status_dot = tk.Label(hf, text="●", fg=GREEN, bg=SURFACE, font=("Segoe UI", 9))
            status_dot.pack(side="left")
            tk.Label(hf, text=gw["name"], fg=TXT, bg=SURFACE,
                     font=("Segoe UI", 11, "bold")).pack(side="left", padx=(4, 0))

            sessions_lbl = tk.Label(f, text="0 phiên · 0 HO", fg=MUTED, bg=SURFACE,
                                    font=("Segoe UI", 9))
            sessions_lbl.pack(anchor="w", pady=(4, 0))

            self.gw_cards[gw["name"]] = {
                "frame": f, "dot": status_dot, "sessions": sessions_lbl
            }

        # Session cards area (scrollable)
        tk.Label(left, text="PHIÊN KẾT NỐI NGƯỜI DÙNG", fg=HINT, bg=BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        sess_outer = tk.Frame(left, bg=BG)
        sess_outer.pack(fill="both", expand=True)

        self.sess_canvas = tk.Canvas(sess_outer, bg=BG, highlightthickness=0)
        sess_scroll = ttk.Scrollbar(sess_outer, orient="vertical",
                                    command=self.sess_canvas.yview)
        self.sess_canvas.configure(yscrollcommand=sess_scroll.set)
        sess_scroll.pack(side="right", fill="y")
        self.sess_canvas.pack(side="left", fill="both", expand=True)

        self.sess_frame = tk.Frame(self.sess_canvas, bg=BG)
        self.sess_win   = self.sess_canvas.create_window((0, 0), window=self.sess_frame,
                                                          anchor="nw")
        self.sess_frame.bind("<Configure>", self._on_sess_resize)
        self.sess_canvas.bind("<Configure>", self._on_canvas_resize)
        self.sess_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # RIGHT: log panel
        right = tk.Frame(body, bg=BG, width=320)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        tk.Label(right, text="NHẬT KÝ SỰ KIỆN", fg=HINT, bg=BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        log_outer = tk.Frame(right, bg=SURFACE, highlightthickness=1,
                             highlightbackground=BORDER)
        log_outer.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_outer, bg=SURFACE, fg=TXT,
            font=("Consolas", 9),
            wrap="word", state="disabled",
            relief="flat", padx=8, pady=6,
            insertbackground=TXT,
            selectbackground=SURFACE2,
        )
        log_scroll = ttk.Scrollbar(log_outer, orient="vertical",
                                   command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        # Text tags màu
        for level, color in LEVEL_COLOR.items():
            self.log_text.tag_config(f"lv_{level}", foreground=color)
        self.log_text.tag_config("time", foreground=HINT)
        self.log_text.tag_config("uid",  foreground=MUTED)

        # Status bar
        self.statusbar = tk.Label(self, text="Đang khởi động…", fg=HINT, bg=SURFACE,
                                  font=("Segoe UI", 8), anchor="w", padx=12)
        self.statusbar.pack(fill="x", side="bottom")

    # ── Scroll helpers ────────────────────────────────────────────────────────

    def _on_sess_resize(self, event):
        self.sess_canvas.configure(scrollregion=self.sess_canvas.bbox("all"))

    def _on_canvas_resize(self, event):
        self.sess_canvas.itemconfig(self.sess_win, width=event.width)

    def _on_mousewheel(self, event):
        self.sess_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg_type, data = self.q.get_nowait()
                if msg_type == "TELEMETRY":
                    self._handle_telemetry(data)
                elif msg_type == "LOG":
                    self._handle_log(data)
                elif msg_type == "GATEWAYS":
                    self._handle_gateways(data)
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    # ── Telemetry → cập nhật card ─────────────────────────────────────────────

    def _handle_telemetry(self, s):
        uid = s["user_id"]
        if uid not in self.session_cards:
            color = SERIES_COLORS[len(self.session_cards) % len(SERIES_COLORS)]
            card  = SessionCard(self.sess_frame, uid, color)
            card.pack(fill="x", pady=(0, 8))
            self.session_cards[uid] = card
        self.session_cards[uid].update_data(s)
        # Cập nhật status bar
        self.statusbar.config(
            text=f"{uid} | {s.get('satellite_id', s.get('sat_id','—'))} "
                 f"elev={s.get('elevation',0):.1f}° C/N={s.get('cn_db',0):.1f}dB "
                 f"| {time.strftime('%H:%M:%S')}"
        )

    # ── Gateway update ────────────────────────────────────────────────────────

    def _handle_gateways(self, gw_dict):
        for name, info in gw_dict.items():
            if name not in self.gw_cards: continue
            card   = self.gw_cards[name]
            status = info.get("status", "ALIVE")
            color  = GREEN if status == "ALIVE" else (RED if status == "DEAD" else AMBER)
            card["dot"].config(fg=color)
            card["frame"].config(highlightbackground=color)
            card["sessions"].config(
                text=f"{info.get('active',0)} phiên · {info.get('total_ho',0)} HO"
            )

    # ── Log ───────────────────────────────────────────────────────────────────

    def _handle_log(self, entry):
        level = entry["level"]
        t     = entry["time"]
        uid   = entry["user_id"]
        msg   = entry["msg"]

        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{t}] ", "time")
        self.log_text.insert("end", f"{level:<10} ", f"lv_{level}")
        self.log_text.insert("end", f"[{uid}] ", "uid")
        self.log_text.insert("end", f"{msg}\n")
        # Giữ tối đa 300 dòng
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 300:
            self.log_text.delete("1.0", "50.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Danh sách người dùng mô phỏng
    users = [
        ("User-HN-01",  21.03, 105.85),   # Hà Nội
        ("User-DN-01",  16.07, 108.22),   # Đà Nẵng
        ("User-HCM-01", 10.82, 106.63),   # TP.HCM
    ]

    print("=" * 60)
    print("  VNU-LEO Tầng 2 — Gateway & Handover GUI")
    print(f"  {len(users)} users · Walker 24/6/1 · 550 km")
    print("=" * 60)

    # Queue truyền event từ asyncio → tkinter
    event_q = queue.Queue()

    # Chạy engine trong thread riêng
    engine_thread = threading.Thread(
        target=start_engine, args=(event_q, users), daemon=True
    )
    engine_thread.start()

    # Khởi động GUI (blocking — chạy trên main thread)
    app = VNULeoDashboard(event_q)
    app.mainloop()


if __name__ == "__main__":
    main()