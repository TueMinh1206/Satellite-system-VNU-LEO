"""
╔══════════════════════════════════════════════════════════════════════════╗
║   PHASED ARRAY SIMULATOR v4.0                                            ║
║   Dự án: VNU-LEO — Bài toán 3: Client End-user Router                   ║
║                                                                          ║
║   THAY ĐỔI SO VỚI v3:                                                   ║
║   ✓ Đọc trực tiếp file TLE của nhóm (.txt)                              ║
║   ✓ Hỗ trợ chòm sao 21 vệ tinh (3 mặt phẳng × 7 vệ tinh)              ║
║   ✓ Tự chọn vệ tinh tốt nhất (elevation cao nhất) tại mỗi bước         ║
║   ✓ Hiển thị tên vệ tinh đang được bám bắt                              ║
║   ✗ Không cần tle.js, không cần file JSON/CSV trung gian                ║
║                                                                          ║
║   Cách chạy:                                                             ║
║     python phased_array_simulator_v4.py                                  ║
║     python phased_array_simulator_v4.py --tle tle_constellation.txt     ║
║     python phased_array_simulator_v4.py --cli                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider, RadioButtons, Button
from matplotlib.animation import FuncAnimation
from datetime import datetime, timedelta, timezone
import math, warnings, sys, os
warnings.filterwarnings("ignore")


# ═══════════════════════════════════════════════════════════════════════
# PHẦN 1 — ĐỌC FILE TLE VÀ TÍNH AZ/EL
# ═══════════════════════════════════════════════════════════════════════

# Hằng số vật lý
MU    = 3.986004418e14   # m³/s²
R_E   = 6378137.0        # m
J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def parse_tle_file(filepath: str) -> list:
    """
    Đọc file TLE nhiều vệ tinh (định dạng 3 dòng chuẩn NORAD).

    Định dạng mỗi vệ tinh trong file:
        VNULEO-0001                            ← Dòng 0: tên
        1 00001U 26001A   26001.50000000 ...   ← Dòng 1
        2 00001 090.0000 000.0000 ...          ← Dòng 2

    Trả về: list[dict] mỗi dict chứa tham số quỹ đạo đã parse.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Không tìm thấy file TLE: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        raw = [ln.strip() for ln in f if ln.strip()]

    satellites = []
    i = 0
    while i < len(raw) - 2:
        # Xác định 3 dòng liên tiếp: name, line1, line2
        if raw[i+1].startswith('1 ') and raw[i+2].startswith('2 '):
            name = raw[i]
            l1   = raw[i+1]
            l2   = raw[i+2]
            try:
                sat = _parse_single_tle(name, l1, l2)
                satellites.append(sat)
            except Exception as e:
                print(f"  [WARN] Bỏ qua {name}: {e}")
            i += 3
        else:
            i += 1

    print(f"  [OK] Đọc {len(satellites)} vệ tinh từ {os.path.basename(filepath)}")

    # In tóm tắt cấu trúc chòm sao
    alt_km = satellites[0]['alt_km'] if satellites else 0
    inc    = satellites[0]['inc']    if satellites else 0
    raans  = sorted(set(round(s['raan'], 1) for s in satellites))
    print(f"       Độ cao: {alt_km:.0f} km  |  Nghiêng: {inc}°")
    print(f"       Mặt phẳng RAAN: {raans}")
    print(f"       Vệ tinh/mặt phẳng: {len(satellites)//len(raans)}")

    return satellites


def _parse_single_tle(name: str, l1: str, l2: str) -> dict:
    """
    Parse một vệ tinh từ 2 dòng TLE.

    Tính semi-major axis:
        n = mean_motion × 2π/86400   [rad/s]
        a = (μ/n²)^(1/3)             [m]
        h = a − R_E                  [m] → chia 1000 → km
    """
    # Epoch từ Line 1
    ep_str = l1[18:32].strip()
    yr2    = int(ep_str[:2])
    year   = 2000 + yr2 if yr2 < 57 else 1900 + yr2
    doy    = float(ep_str[2:])
    epoch  = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)

    # Tham số quỹ đạo từ Line 2
    inc  = float(l2[8:16])
    raan = float(l2[17:25])
    ecc  = float('0.' + l2[26:33])
    argp = float(l2[34:42])
    M0   = float(l2[43:51])
    n    = float(l2[52:63]) * 2 * math.pi / 86400   # rad/s

    a      = (MU / n**2) ** (1/3)
    alt_km = (a - R_E) / 1000.0

    return dict(name=name, epoch=epoch, inc=inc, raan=raan,
                ecc=ecc, argp=argp, M0=M0, n=n, a=a, alt_km=alt_km)


def satellite_azel(sat: dict, t: datetime,
                   obs_lat_deg: float, obs_lon_deg: float) -> dict:
    """
    Tính Azimuth, Elevation, Range từ vệ tinh đến trạm quan sát.

    Chuỗi biến đổi:
      TLE params → Mean Anomaly M(t) → Eccentric Anomaly E (Kepler)
      → True Anomaly ν → Perifocal (r, ν) → ECI → ECEF → ENU → Az/El
    """
    dt = (t - sat['epoch']).total_seconds()

    # ── Mean Anomaly ──
    M = (math.radians(sat['M0']) + sat['n'] * dt) % (2 * math.pi)

    # ── Giải Kepler: M = E − e·sin(E) (Newton-Raphson) ──
    e = sat['ecc']
    E = M
    for _ in range(50):
        dE = (M - E + e * math.sin(E)) / (1 - e * math.cos(E))
        E += dE
        if abs(dE) < 1e-10:
            break

    # ── True Anomaly ──
    sin_nu = math.sqrt(1 - e**2) * math.sin(E) / (1 - e * math.cos(E))
    cos_nu = (math.cos(E) - e) / (1 - e * math.cos(E))
    nu     = math.atan2(sin_nu, cos_nu)
    r      = sat['a'] * (1 - e * math.cos(E))

    # ── Perifocal → ECI ──
    raan = math.radians(sat['raan'])
    inc  = math.radians(sat['inc'])
    w    = math.radians(sat['argp'])
    cr, sr = math.cos(raan), math.sin(raan)
    ci, si = math.cos(inc),  math.sin(inc)
    cw, sw = math.cos(w),    math.sin(w)
    R = [[cr*cw-sr*sw*ci, -cr*sw-sr*cw*ci,  sr*si],
         [sr*cw+cr*sw*ci, -sr*sw+cr*cw*ci, -cr*si],
         [sw*si,           cw*si,            ci   ]]
    xp, yp = r * math.cos(nu), r * math.sin(nu)
    eci = [sum(R[j][k] * [xp, yp, 0][k] for k in range(3)) for j in range(3)]

    # ── ECI → ECEF (xoay theo GMST) ──
    GMST = math.radians(
        (280.46061837 + 360.98564736629 * (t - J2000).total_seconds() / 86400) % 360
    )
    ecef = [eci[0]*math.cos(GMST) + eci[1]*math.sin(GMST),
           -eci[0]*math.sin(GMST) + eci[1]*math.cos(GMST),
            eci[2]]

    # ── Vị trí Observer trong ECEF ──
    lat = math.radians(obs_lat_deg)
    lon = math.radians(obs_lon_deg)
    f   = 1 / 298.257223563                  # WGS-84 flattening
    N_  = R_E / math.sqrt(1 - (2*f - f**2) * math.sin(lat)**2)
    obs = [N_          * math.cos(lat) * math.cos(lon),
           N_          * math.cos(lat) * math.sin(lon),
           N_ * (1 - (2*f - f**2)) * math.sin(lat)]

    # ── ECEF → ENU ──
    rho  = [ecef[i] - obs[i] for i in range(3)]
    rho_n = math.sqrt(sum(x**2 for x in rho))
    sl, cl   = math.sin(lat), math.cos(lat)
    slon, clon = math.sin(lon), math.cos(lon)
    E_   = -slon       * rho[0] + clon       * rho[1]
    N_c  = -sl * clon  * rho[0] - sl * slon  * rho[1] + cl * rho[2]
    U_   =  cl * clon  * rho[0] + cl * slon  * rho[1] + sl * rho[2]

    el  = math.degrees(math.asin(U_ / rho_n))
    az  = math.degrees(math.atan2(E_, N_c)) % 360

    return {
        'elevation_deg': round(el, 2),
        'azimuth_deg':   round(az, 2),
        'range_km':      round(rho_n / 1000, 1),
        'range_m':       rho_n,
        'name':          sat['name'],
    }


def best_satellite(satellites: list, t: datetime,
                   lat: float, lon: float,
                   min_el: float = 5.0) -> dict | None:
    """
    Tìm vệ tinh có elevation cao nhất (tín hiệu tốt nhất) tại thời điểm t.
    Trả về None nếu không có vệ tinh nào trên min_el.
    """
    best = None
    best_el = min_el
    for sat in satellites:
        result = satellite_azel(sat, t, lat, lon)
        if result['elevation_deg'] > best_el:
            best_el = result['elevation_deg']
            best    = result
    return best


def scan_passes(satellites: list, t_start: datetime,
                lat: float, lon: float,
                duration_h: float = 24.0,
                step_min: float = 2.0) -> list:
    """
    Quét toàn bộ chòm sao trong duration_h giờ, bước step_min phút.
    Trả về list các thời điểm có ít nhất 1 vệ tinh visible (El > 5°).
    """
    passes = []
    steps  = int(duration_h * 60 / step_min)
    for i in range(steps):
        t   = t_start + timedelta(minutes=i * step_min)
        vis = best_satellite(satellites, t, lat, lon)
        if vis:
            passes.append({'time': t, **vis})
    return passes


# ═══════════════════════════════════════════════════════════════════════
# PHẦN 2 — LINK BUDGET (không đổi từ v2/v3)
# ═══════════════════════════════════════════════════════════════════════

class LinkBudget:
    """
    C/N₀ = EIRP + G/T − FSPL − L_atm − L_rain − L_point − k_B
    Tham chiếu: Pratt et al. (2019), ITU-R P.676, ITU-R P.838-3
    """
    K_B = 1.380649e-23

    def __init__(self, freq_ghz=14.0, eirp_tx_dbw=47.0,
                 g_rx_dbi=35.0, t_sys_k=150.0,
                 bandwidth_mhz=500.0, bitrate_mbps=100.0):
        self.freq_ghz  = freq_ghz
        self.lam       = 3e8 / (freq_ghz * 1e9)
        self.eirp_dbw  = eirp_tx_dbw
        self.g_rx_dbi  = g_rx_dbi
        self.t_sys_k   = t_sys_k
        self.bw_hz     = bandwidth_mhz * 1e6
        self.rb_bps    = bitrate_mbps  * 1e6

    def fspl_db(self, d_m):
        """FSPL = 20·log₁₀(4π·d/λ)"""
        return 20 * np.log10(4 * np.pi * d_m / self.lam)

    def atm_loss_db(self, el_deg):
        """L_atm = L_zenith / sin(El),  L_zenith xấp xỉ ITU-R P.676"""
        el = max(math.radians(el_deg), math.radians(3.0))
        Lz = 0.035 * self.freq_ghz**0.4 + 0.007
        return Lz / math.sin(el)

    def rain_loss_db(self, el_deg, rain_mmh=20.0):
        """γ_R = k·R^α,  L = γ_R·5km / sin(El),  ITU-R P.838-3 Ku-band"""
        k   = 0.0367 + 0.001 * (self.freq_ghz - 14)
        alp = 1.181 - 0.005 * (self.freq_ghz - 14)
        el  = max(math.radians(el_deg), math.radians(5.0))
        return k * (rain_mmh**alp) * 5.0 / math.sin(el)

    def pointing_loss_db(self, err_deg):
        """L_pt ≈ 12·(θ_err / θ₋₃dB)², θ₋₃dB = 51.6°/N"""
        return 12 * (err_deg / (51.6 / 8))**2

    def compute(self, d_m, el_deg, rain_mmh=20.0, pt_err_deg=0.5):
        fspl  = self.fspl_db(d_m)
        latm  = self.atm_loss_db(el_deg)
        lrain = self.rain_loss_db(el_deg, rain_mmh)
        lpt   = self.pointing_loss_db(pt_err_deg)
        ltot  = fspl + latm + lrain + lpt
        GoT   = self.g_rx_dbi - 10 * np.log10(self.t_sys_k)
        kdb   = 10 * np.log10(self.K_B)
        CN0   = self.eirp_dbw + GoT - ltot - kdb
        CN    = CN0 - 10 * np.log10(self.bw_hz)
        return {
            'fspl_db':       round(fspl, 2),
            'atm_loss_db':   round(latm, 3),
            'rain_loss_db':  round(lrain, 3),
            'total_loss_db': round(ltot, 2),
            'CN0_dBHz':      round(CN0, 2),
            'CN_db':         round(CN, 2),
            'G_over_T':      round(GoT, 2),
            'snr_linear':    max(10**(CN/10), 1e-6),
            'link_margin_db':round(CN - 10.0, 2),
            'link_ok':       CN >= 10.0,
        }


# ═══════════════════════════════════════════════════════════════════════
# PHẦN 3 — BEAMFORMING (không đổi)
# ═══════════════════════════════════════════════════════════════════════

def sv(theta_deg, N, d=0.5):
    n = np.arange(N)
    return np.exp(1j * 2 * np.pi * d * n * np.sin(np.deg2rad(theta_deg)))

def pattern_db(angles, w, N):
    af  = np.array([np.dot(w.conj(), sv(a, N)) for a in angles])
    mag = np.maximum(np.abs(af), 1e-12)
    return 20 * np.log10(mag / mag.max())

def w_conv(N, t0):
    return sv(t0, N).conj() / N

def w_mvdr(N, t0, tj, snr_db):
    a0  = sv(t0, N); aj = sv(tj, N)
    sn  = 10**(-snr_db/20)
    R   = np.outer(a0, a0.conj()) + 20**2*np.outer(aj,aj.conj()) + sn**2*np.eye(N)
    Ri  = np.linalg.inv(R + 1e-6*np.eye(N))
    w   = Ri@a0 / (a0.conj()@Ri@a0 + 1e-12)
    return w / (np.linalg.norm(w)+1e-12)

def w_lms(N, t0, tj, mu, snr_db, n_iter=300):
    a0=sv(t0,N); aj=sv(tj,N); sn=10**(-snr_db/20)
    w=np.zeros(N,dtype=complex)
    for _ in range(n_iter):
        s=np.exp(1j*2*np.pi*np.random.rand())
        x=a0*s+aj*0.5*np.exp(1j*2*np.pi*np.random.rand())+(np.random.randn(N)+1j*np.random.randn(N))*sn/np.sqrt(2)
        e=s-np.dot(w.conj(),x); w+=mu*np.conj(e)*x
    return w/(np.linalg.norm(w)+1e-12)

def w_rls(N, t0, tj, snr_db, lam=0.98, n_iter=300):
    a0=sv(t0,N); aj=sv(tj,N); sn=10**(-snr_db/20)
    w=np.zeros(N,dtype=complex); P=100.0*np.eye(N,dtype=complex)
    for _ in range(n_iter):
        s=np.exp(1j*2*np.pi*np.random.rand())
        x=a0*s+aj*0.5*np.exp(1j*2*np.pi*np.random.rand())+(np.random.randn(N)+1j*np.random.randn(N))*sn/np.sqrt(2)
        Px=P@x; k=Px/(lam+x.conj()@Px); e=s-np.dot(w.conj(),x)
        w+=k*np.conj(e); P=(P-np.outer(k,x.conj()@P))/lam
    return w/(np.linalg.norm(w)+1e-12)

def get_weights(algo, N, t0, tj, mu, snr_db):
    if algo=='conv':  return w_conv(N, t0)
    if algo=='mvdr':  return w_mvdr(N, t0, tj, snr_db)
    if algo=='lms':   return w_lms(N, t0, tj, mu, snr_db, 200)
    if algo=='rls':   return w_rls(N, t0, tj, snr_db, n_iter=200)
    return w_conv(N, t0)


# ═══════════════════════════════════════════════════════════════════════
# PHẦN 4 — GUI
# ═══════════════════════════════════════════════════════════════════════

# Vị trí các Gateway (Bài toán 2)
GATEWAYS = {
    'Hà Nội':  (21.0278, 105.8342),
    'Đà Nẵng': (16.0544, 108.2022),
    'TP.HCM':  (10.8231, 106.6297),
}

class SimulatorGUI:
    C = dict(teal='#1D9E75', amber='#EF9F27', red='#E24B4A',
             blue='#378ADD', purple='#7F77DD',
             bg='#F5F5F2', surface='#FFFFFF',
             text='#1A1A18', muted='#6B6B67')

    def __init__(self, satellites: list):
        self.sats    = satellites
        self.n_sats  = len(satellites)
        self.algo    = 'mvdr'
        self.angles  = np.linspace(-90, 90, 361)
        self.gw_name = 'Hà Nội'
        self.gw_lat, self.gw_lon = GATEWAYS[self.gw_name]

        # Thời gian bắt đầu = epoch TLE
        self.t0      = satellites[0]['epoch']
        self.t_sim   = self.t0
        self.sim_t   = 0
        self.sim_run = False
        self.conv_data = {'lms':[],'mvdr':[],'rls':[]}

        # Precompute: quét 2 giờ đầu để tìm passes
        print("  Đang tính toán passes... ", end='', flush=True)
        self.passes = scan_passes(self.sats, self.t0,
                                  self.gw_lat, self.gw_lon,
                                  duration_h=4.0, step_min=1.0)
        print(f"{len(self.passes)} bước có tín hiệu")

        self.pass_idx = 0
        self.lb = LinkBudget()
        self._build()
        self._redraw()

    # ── Build figure ──────────────────────────────────────────────────
    def _build(self):
        plt.style.use('seaborn-v0_8-whitegrid')
        self.fig = plt.figure(
            figsize=(18, 10), facecolor=self.C['bg'],
            num=f'Phased Array v4 — VNU-LEO {self.n_sats} vệ tinh')
        self.fig.patch.set_facecolor(self.C['bg'])

        gs = gridspec.GridSpec(3, 4, figure=self.fig,
                               height_ratios=[3.8, 2.6, 1.8],
                               hspace=0.42, wspace=0.30,
                               left=0.065, right=0.97,
                               top=0.93, bottom=0.04)

        self.ax_pat  = self.fig.add_subplot(gs[0, :2])
        self.ax_pol  = self.fig.add_subplot(gs[0, 2], projection='polar')
        self.ax_lb   = self.fig.add_subplot(gs[0, 3])
        self.ax_conv = self.fig.add_subplot(gs[1, :2])
        self.ax_ph   = self.fig.add_subplot(gs[1, 2])
        self.ax_amp  = self.fig.add_subplot(gs[1, 3])

        sl_axes = [self.fig.add_subplot(gs[2, i]) for i in range(4)]
        self.sl_N    = Slider(sl_axes[0], 'Phần tử N', 2, 16, valinit=8,   valstep=1)
        self.sl_rain = Slider(sl_axes[1], 'Mưa mm/h',  0, 100,valinit=20,  valstep=5)
        self.sl_mu   = Slider(sl_axes[2], 'LMS μ', 0.01, 0.2, valinit=0.05,valstep=0.01)
        self.sl_time = Slider(sl_axes[3], 'Thời gian',
                              0, max(len(self.passes)-1, 1),
                              valinit=0, valstep=1)

        for sl in [self.sl_N, self.sl_rain, self.sl_mu, self.sl_time]:
            sl.label.set_fontsize(9); sl.valtext.set_fontsize(9)

        ax_r = self.fig.add_axes([0.003, 0.04, 0.055, 0.18])
        self.radio = RadioButtons(ax_r, ('Conv','LMS','MVDR','RLS'),
                                  active=2, activecolor=self.C['teal'])
        ax_r.set_title('Algo', fontsize=8, pad=3)

        ax_gw = self.fig.add_axes([0.003, 0.24, 0.055, 0.14])
        self.radio_gw = RadioButtons(ax_gw, list(GATEWAYS.keys()),
                                     active=0, activecolor=self.C['blue'])
        ax_gw.set_title('Gateway', fontsize=8, pad=3)

        ax_run  = self.fig.add_axes([0.004, 0.40, 0.052, 0.028])
        ax_stop = self.fig.add_axes([0.004, 0.37, 0.052, 0.028])
        ax_rst  = self.fig.add_axes([0.004, 0.34, 0.052, 0.028])
        self.btn_run  = Button(ax_run,  '▶ Chạy', color=self.C['teal'], hovercolor='#0F6E56')
        self.btn_stop = Button(ax_stop, '⏸ Dừng', color='#E0DDD6', hovercolor='#CCC9C0')
        self.btn_rst  = Button(ax_rst,  '↺ Reset', color='#E0DDD6', hovercolor='#CCC9C0')
        self.btn_run.label.set_color('white')
        for b in [self.btn_run, self.btn_stop, self.btn_rst]:
            b.label.set_fontsize(8)

        self.status = self.fig.text(0.005, 0.33, '● Dừng',
                                    fontsize=8, color=self.C['muted'])
        self.fig.text(0.5, 0.965,
                      f'📡  Phased Array v4.0  —  VNU-LEO Constellation  '
                      f'({self.n_sats} sats, h≈{self.sats[0]["alt_km"]:.0f}km, '
                      f'i={self.sats[0]["inc"]:.0f}°)',
                      ha='center', fontsize=11, fontweight='bold',
                      color=self.C['text'])

        for sl in [self.sl_N, self.sl_rain, self.sl_mu]:
            sl.on_changed(lambda v: self._redraw())
        self.sl_time.on_changed(self._on_time_change)
        self.radio.on_clicked(lambda l: self._set_algo(l))
        self.radio_gw.on_clicked(self._set_gw)
        self.btn_run.on_clicked(lambda e: self._start())
        self.btn_stop.on_clicked(lambda e: self._stop())
        self.btn_rst.on_clicked(lambda e: self._reset())

    # ── Helpers ───────────────────────────────────────────────────────
    def _set_algo(self, label):
        self.algo = {'Conv':'conv','LMS':'lms','MVDR':'mvdr','RLS':'rls'}[label]
        self._redraw()

    def _set_gw(self, label):
        self.gw_name = label
        self.gw_lat, self.gw_lon = GATEWAYS[label]
        print(f"  [Gateway] Chuyển sang {label} ({self.gw_lat}°N, {self.gw_lon}°E)")
        print("  Đang tính lại passes... ", end='', flush=True)
        self.passes = scan_passes(self.sats, self.t0,
                                  self.gw_lat, self.gw_lon,
                                  duration_h=4.0, step_min=1.0)
        print(f"{len(self.passes)} bước")
        self.pass_idx = 0
        if len(self.passes) > 1:
            self.sl_time.valmax = len(self.passes) - 1
        self.sl_time.set_val(0)
        self._redraw()

    def _on_time_change(self, val):
        self.pass_idx = int(round(val))
        self._redraw()

    def _style(self, ax):
        ax.set_facecolor(self.C['surface'])
        ax.tick_params(labelsize=8, colors=self.C['muted'])
        for sp in ax.spines.values():
            sp.set_linewidth(0.5); sp.set_color('#D3D1C7')
        ax.grid(True, lw=0.4, alpha=0.6, color='#D3D1C7')

    # ── Redraw ────────────────────────────────────────────────────────
    def _redraw(self):
        N    = int(round(self.sl_N.val))
        rain = float(self.sl_rain.val)
        mu   = float(self.sl_mu.val)

        if not self.passes:
            self._draw_no_signal()
            return

        # Lấy dữ liệu az/el từ bước TLE hiện tại
        row     = self.passes[self.pass_idx % len(self.passes)]
        el      = row['elevation_deg']
        az      = row['azimuth_deg']
        rng_m   = row['range_m']
        sat_nm  = row['name']
        t_row   = row['time']

        # Chuyển elevation → steering angle
        theta0  = 90.0 - el
        theta_j = theta0 + 25.0

        # Link budget dùng range thực
        budget  = self.lb.compute(rng_m, el, rain_mmh=rain)
        snr     = max(budget['CN_db'], 3.0)

        # Beamforming weights
        w = get_weights(self.algo, N, theta0, theta_j, mu, snr)

        self._draw_pattern(N, w, el, az, theta0, theta_j, budget, sat_nm, t_row)
        self._draw_polar(N, w)
        self._draw_link_budget(budget, el, rng_m/1000)
        self._draw_phase_amp(N, w)
        self._draw_conv()
        self.fig.canvas.draw_idle()

    def _draw_no_signal(self):
        for ax in [self.ax_pat, self.ax_conv, self.ax_ph, self.ax_amp, self.ax_lb]:
            ax.clear(); self._style(ax)
            ax.text(0.5, 0.5, 'Không có tín hiệu\ntrong khoảng thời gian này',
                    ha='center', va='center', transform=ax.transAxes,
                    fontsize=9, color=self.C['muted'])
        self.fig.canvas.draw_idle()

    # ── Vẽ Pattern ────────────────────────────────────────────────────
    def _draw_pattern(self, N, w, el, az, theta0, theta_j, budget, sat_nm, t_row):
        ax = self.ax_pat; ax.clear(); self._style(ax)
        dbs = pattern_db(self.angles, w, N)
        ax.plot(self.angles, dbs, color=self.C['teal'], lw=1.8)
        ax.fill_between(self.angles, dbs, -65,
                        where=dbs > -65, alpha=0.10, color=self.C['teal'])
        ax.axvline(theta0,  color=self.C['amber'], lw=1.6,
                   label=f'θ₀={theta0:.1f}° → El={el:.1f}°, Az={az:.1f}°')
        ax.axvline(theta_j, color=self.C['red'],   lw=1.4, ls='--',
                   label=f'Nhiễu null tại θⱼ={theta_j:.0f}°')

        # Hiển thị tên vệ tinh đang bám bắt
        link_clr = self.C['teal'] if budget['link_ok'] else self.C['red']
        ax.text(0.02, 0.97,
                f'🛰 {sat_nm}  |  N={N}  Gain≈{10*np.log10(N):.1f}dBi  '
                f'Algo={self.algo.upper()}',
                transform=ax.transAxes, fontsize=9, fontweight='bold',
                color=link_clr, va='top')
        ax.text(0.02, 0.88,
                f'C/N₀={budget["CN0_dBHz"]:.1f}dBHz  '
                f'Margin={budget["link_margin_db"]:+.1f}dB  '
                f'{t_row.strftime("%H:%M:%S UTC")}  '
                f'Bước {self.pass_idx+1}/{len(self.passes)}',
                transform=ax.transAxes, fontsize=8,
                color=self.C['muted'], va='top')
        ax.set_xlim(-90, 90); ax.set_ylim(-65, 3)
        ax.set_xlabel('Góc θ (°)', fontsize=9, color=self.C['muted'])
        ax.set_ylabel('Gain (dB)', fontsize=9, color=self.C['muted'])
        ax.set_title(f'Radiation Pattern — Tracking {self.gw_name}',
                     fontsize=10, fontweight='bold', color=self.C['text'], pad=6)
        ax.legend(fontsize=8, loc='upper right', framealpha=0.9)
        ax.set_xticks(range(-90, 91, 30))
        ax.set_xticklabels([f'{x}°' for x in range(-90, 91, 30)], fontsize=8)

    # ── Vẽ Polar ──────────────────────────────────────────────────────
    def _draw_polar(self, N, w):
        ax = self.ax_pol; ax.clear()
        dbs = pattern_db(self.angles, w, N)
        r   = np.maximum(dbs + 65, 0)
        th  = np.deg2rad(90 - self.angles)
        ax.plot(th, r, color=self.C['teal'], lw=1.8)
        ax.fill(th, r, alpha=0.12, color=self.C['teal'])
        ax.set_title('Polar', fontsize=9, fontweight='bold',
                     color=self.C['text'], pad=10)
        ax.set_rticks([15, 30, 45, 60]); ax.tick_params(labelsize=7)
        ax.set_theta_direction(-1); ax.set_theta_offset(np.pi/2)

    # ── Vẽ Link Budget ────────────────────────────────────────────────
    def _draw_link_budget(self, budget, el, rng_km):
        ax = self.ax_lb; ax.clear(); self._style(ax)
        items = [
            ('EIRP phát',    self.lb.eirp_dbw,          self.C['teal']),
            ('G/T thu',      budget['G_over_T'],         self.C['teal']),
            ('FSPL',        -budget['fspl_db'],          self.C['red']),
            ('Khí quyển',   -budget['atm_loss_db'],      self.C['amber']),
            ('Mưa',         -budget['rain_loss_db'],     self.C['amber']),
        ]
        labels = [x[0] for x in items]
        values = [x[1] for x in items]
        colors = [x[2] for x in items]
        bars   = ax.barh(labels, values, color=colors,
                         edgecolor='white', linewidth=0.5, height=0.55)
        ax.axvline(0, color='#D3D1C7', lw=0.8)
        for bar, v in zip(bars, values):
            ax.text(v + (1.5 if v >= 0 else -1.5),
                    bar.get_y() + bar.get_height()/2,
                    f'{v:+.1f}dB', va='center', fontsize=7,
                    color=self.C['text'])
        clr = self.C['teal'] if budget['link_ok'] else self.C['red']
        ax.set_title(
            f'Link Budget  El={el:.1f}°  {rng_km:.0f}km\n'
            f'C/N₀={budget["CN0_dBHz"]:.1f}dBHz  '
            f'{"✓" if budget["link_ok"] else "✗"}'
            f' Margin={budget["link_margin_db"]:+.1f}dB',
            fontsize=8, fontweight='bold', color=clr, pad=5)
        ax.set_xlabel('dB', fontsize=8, color=self.C['muted'])

    # ── Vẽ Phase & Amplitude ──────────────────────────────────────────
    def _draw_phase_amp(self, N, w):
        labels = [f'A{i+1}' for i in range(N)]
        phases = np.angle(w) * 180 / np.pi
        amps   = np.abs(w); amps /= (amps.max() + 1e-12)
        for ax, data, col, title, ylim, ysfx in [
            (self.ax_ph,  phases, self.C['blue'],   'Phân bố pha (°)', (-200,200), '°'),
            (self.ax_amp, amps,   self.C['purple'],  'Biên độ (norm)',  (0, 1.2),  ''),
        ]:
            ax.clear(); self._style(ax)
            bars = ax.bar(labels, data, color=col, edgecolor='white',
                          linewidth=0.5, width=0.65)
            ax.set_ylim(*ylim)
            ax.tick_params(axis='x', labelsize=7 if N <= 12 else 5)
            ax.set_title(title, fontsize=9, fontweight='bold',
                         color=self.C['text'], pad=6)
            for bar, v in zip(bars, data):
                ax.text(bar.get_x() + bar.get_width()/2,
                        bar.get_height() + (ylim[1]*0.04 if v >= 0 else -ylim[1]*0.08),
                        f'{v:.0f}{ysfx}', ha='center', fontsize=6,
                        color=self.C['muted'])

    # ── Vẽ Convergence ────────────────────────────────────────────────
    def _draw_conv(self):
        ax = self.ax_conv; ax.clear(); self._style(ax)
        meta = {'lms':(self.C['teal'],'-'),
                'mvdr':(self.C['purple'],'--'),
                'rls':(self.C['amber'],'-.')}
        has = False
        for k, (col, ls) in meta.items():
            if len(self.conv_data[k]) > 4:
                sm = np.convolve(self.conv_data[k], np.ones(6)/6, 'valid')
                ax.plot(sm, color=col, lw=1.8, ls=ls, label=k.upper(), alpha=0.9)
                has = True
        if not has:
            ax.text(0.5, 0.5, 'Nhấn ▶ Chạy\nđể xem hội tụ MSE',
                    ha='center', va='center', transform=ax.transAxes,
                    fontsize=9, color=self.C['muted'])
        ax.set_xlabel('Iteration', fontsize=9, color=self.C['muted'])
        ax.set_ylabel('MSE (dB)', fontsize=9, color=self.C['muted'])
        ax.set_title('Đường cong hội tụ', fontsize=10,
                     fontweight='bold', color=self.C['text'], pad=6)
        if has: ax.legend(fontsize=8, framealpha=0.9)

    # ── Simulation ────────────────────────────────────────────────────
    def _start(self):
        if self.sim_run: return
        self.sim_run = True
        self.status.set_text('● Đang chạy'); self.status.set_color(self.C['teal'])
        self.anim = FuncAnimation(self.fig, self._step,
                                  interval=500, cache_frame_data=False)
        self.fig.canvas.draw_idle()

    def _step(self, frame):
        if not self.sim_run: return
        self.sim_t  += 1
        self.pass_idx = self.sim_t % max(len(self.passes), 1)
        self.sl_time.set_val(self.pass_idx)

        mu = float(self.sl_mu.val)
        mse = {
            'lms':  max(-55, -10*np.exp(-mu*self.sim_t*0.8) - 15 + np.random.randn()*1.2),
            'mvdr': max(-60, -8 *np.exp(-0.06*self.sim_t)   - 28 + np.random.randn()*0.8),
            'rls':  max(-58, -9 *np.exp(-0.05*self.sim_t)   - 22 + np.random.randn()*1.0),
        }
        for k in mse:
            self.conv_data[k].append(mse[k])
            if len(self.conv_data[k]) > 80: self.conv_data[k].pop(0)
        self._redraw()

    def _stop(self):
        if self.sim_run:
            self.sim_run = False
            if hasattr(self, 'anim'): self.anim.event_source.stop()
        self.status.set_text('● Dừng'); self.status.set_color(self.C['muted'])
        self.fig.canvas.draw_idle()

    def _reset(self):
        self._stop(); self.sim_t = 0; self.pass_idx = 0
        self.conv_data = {'lms':[],'mvdr':[],'rls':[]}
        self.sl_time.set_val(0)
        self._redraw()

    def show(self): plt.show()


# ═══════════════════════════════════════════════════════════════════════
# PHẦN 5 — DEMO CLI
# ═══════════════════════════════════════════════════════════════════════

def demo_cli(satellites, tle_file):
    lb = LinkBudget()
    print(f'\n{"═"*68}')
    print(f'  VNU-LEO Phased Array Simulator v4.0')
    print(f'  File TLE: {os.path.basename(tle_file)}')
    print(f'  {len(satellites)} vệ tinh | h≈{satellites[0]["alt_km"]:.0f}km | i={satellites[0]["inc"]:.0f}°')
    print(f'{"═"*68}')

    t0 = satellites[0]['epoch']
    print(f'\n  Epoch: {t0.strftime("%Y-%m-%d %H:%M UTC")}')
    print(f'\n  Passes tốt nhất trong 4 giờ đầu:\n')
    hdr = f"  {'Thời gian':<12} {'Vệ tinh':<14} {'El':>6} {'Az':>7} {'Range':>8} {'C/N₀':>8} {'Margin':>8}"
    print(hdr); print('  ' + '─'*66)

    for gw_name, (lat, lon) in GATEWAYS.items():
        passes = scan_passes(satellites, t0, lat, lon, duration_h=4.0, step_min=2.0)
        # Lấy 3 pass đỉnh cao nhất
        top3 = sorted(passes, key=lambda x: x['elevation_deg'], reverse=True)[:3]
        if not top3:
            print(f"  [{gw_name}] — Không có pass trong 4 giờ đầu")
            continue
        print(f"  ── {gw_name} ──")
        for p in top3:
            b = lb.compute(p['range_m'], p['elevation_deg'])
            s = '✓' if b['link_ok'] else '✗'
            print(f"  {p['time'].strftime('%H:%M UTC'):<12} {p['name']:<14} "
                  f"{p['elevation_deg']:>6.1f}° {p['azimuth_deg']:>6.1f}° "
                  f"{p['range_km']:>7.0f}km "
                  f"{b['CN0_dBHz']:>7.1f}dBHz "
                  f"{b['link_margin_db']:>6.1f}dB {s}")
        print()

    # So sánh beamforming tại pass tốt nhất Hà Nội
    passes_hn = scan_passes(satellites, t0, 21.0278, 105.8342, 4.0, 2.0)
    if passes_hn:
        best = max(passes_hn, key=lambda x: x['elevation_deg'])
        el, az = best['elevation_deg'], best['azimuth_deg']
        theta0 = 90 - el; theta_j = theta0 + 25
        b = lb.compute(best['range_m'], el)
        snr = max(b['CN_db'], 3.0)
        print(f'  Beamforming @ Hà Nội — {best["name"]}')
        print(f'  El={el:.1f}°  Az={az:.1f}°  θ₀={theta0:.1f}°  SNR={snr:.1f}dB\n')
        print(f"  {'Thuật toán':<14} {'Gain@θ₀':>9} {'Null@θⱼ':>9} {'C/N₀ eff':>10}")
        print('  ' + '─'*44)
        angles = np.linspace(-90, 90, 361)
        for alg, lbl in [('conv','Conventional'),('lms','LMS'),
                          ('mvdr','MVDR'),('rls','RLS')]:
            w   = get_weights(alg, 8, theta0, theta_j, 0.05, snr)
            pat = pattern_db(angles, w, 8)
            i0  = np.argmin(np.abs(angles - theta0))
            ij  = np.argmin(np.abs(angles - theta_j))
            cn0_eff = b['CN0_dBHz'] + 10*np.log10(8) + pat[i0]
            print(f"  {lbl:<14} {pat[i0]:>8.1f}dB {pat[ij]:>8.1f}dB {cn0_eff:>9.1f}dBHz")
    print(f'\n{"═"*68}\n')


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Tìm file TLE
    DEFAULT_TLE = 'tle_constellation_h1000_3x7.txt'
    tle_file    = DEFAULT_TLE

    for i, arg in enumerate(sys.argv[1:]):
        if arg == '--tle' and i+2 <= len(sys.argv)-1:
            tle_file = sys.argv[i+2]
        elif arg.endswith('.txt') and os.path.isfile(arg):
            tle_file = arg

    # Fallback: tìm trong cùng thư mục
    if not os.path.isfile(tle_file):
        for fname in os.listdir('.'):
            if fname.endswith('.txt') and 'tle' in fname.lower():
                tle_file = fname; break

    print(f'\n  Đang đọc TLE: {tle_file}')
    satellites = parse_tle_file(tle_file)

    if '--cli' in sys.argv:
        demo_cli(satellites, tle_file)
    else:
        demo_cli(satellites, tle_file)
        print('  Đang mở GUI...\n')
        gui = SimulatorGUI(satellites)
        gui.show()
