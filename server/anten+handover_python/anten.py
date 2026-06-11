"""
anten.py — beamforming và link budget cho VNU-LEO API
Chỉ chứa các thành phần cần thiết cho FastAPI bridge.
"""

import math
import numpy as np

# ══════════════════════════════════════════════════════════════════════════════
# Link Budget (tính toán ngân sách đường truyền)
# ══════════════════════════════════════════════════════════════════════════════

class LinkBudget:
    """
    Link budget cho đường xuống vệ tinh.
    C/N₀ = EIRP + G/T − FSPL − L_atm − L_rain − L_point − k_B
    """

    K_B = 1.380649e-23  # Boltzmann constant

    def __init__(self, freq_ghz: float = 14.0,
                 eirp_tx_dbw: float = 47.0,
                 g_rx_dbi: float = 35.0,
                 t_sys_k: float = 150.0,
                 bandwidth_mhz: float = 500.0,
                 bitrate_mbps: float = 100.0):
        self.freq_ghz = freq_ghz
        self.lam = 3e8 / (freq_ghz * 1e9)
        self.eirp_dbw = eirp_tx_dbw
        self.g_rx_dbi = g_rx_dbi
        self.t_sys_k = t_sys_k
        self.bw_hz = bandwidth_mhz * 1e6
        self.rb_bps = bitrate_mbps * 1e6

    def fspl_db(self, d_m: float) -> float:
        """Free Space Path Loss (FSPL) = 20·log₁₀(4π·d/λ)"""
        return 20 * np.log10(4 * np.pi * d_m / self.lam)

    def atm_loss_db(self, el_deg: float) -> float:
        """Suy hao khí quyển, phụ thuộc góc ngẩng."""
        el = max(math.radians(el_deg), math.radians(3.0))
        Lz = 0.035 * self.freq_ghz ** 0.4 + 0.007
        return Lz / math.sin(el)

    def rain_loss_db(self, el_deg: float, rain_mmh: float = 20.0) -> float:
        """Suy hao do mưa theo ITU-R P.838-3 (Ku-band)."""
        k = 0.0367 + 0.001 * (self.freq_ghz - 14)
        alp = 1.181 - 0.005 * (self.freq_ghz - 14)
        el = max(math.radians(el_deg), math.radians(5.0))
        return k * (rain_mmh ** alp) * 5.0 / math.sin(el)

    def pointing_loss_db(self, err_deg: float = 0.5, N: int = 8) -> float:
        """Suy hao do lệch hướng, θ₋₃dB ≈ 51.6°/N."""
        theta_3db = 51.6 / N
        return 12 * (err_deg / theta_3db) ** 2

    def compute(self, d_m: float, el_deg: float,
                rain_mmh: float = 20.0,
                point_err_deg: float = 0.5,
                N_array: int = 8) -> dict:
        """
        Tính toán link budget.
        Trả về các giá trị chính: C/N₀, C/N, margin,...
        """
        fspl = self.fspl_db(d_m)
        latm = self.atm_loss_db(el_deg)
        lrain = self.rain_loss_db(el_deg, rain_mmh)
        lpoint = self.pointing_loss_db(point_err_deg, N_array)
        ltot = fspl + latm + lrain + lpoint
        GoT = self.g_rx_dbi - 10 * np.log10(self.t_sys_k)
        k_db = 10 * np.log10(self.K_B)
        cn0 = self.eirp_dbw + GoT - ltot - k_db
        cn = cn0 - 10 * np.log10(self.bw_hz)
        return {
            'fspl_db': round(fspl, 2),
            'atm_loss_db': round(latm, 3),
            'rain_loss_db': round(lrain, 3),
            'point_loss_db': round(lpoint, 2),
            'total_loss_db': round(ltot, 2),
            'CN0_dBHz': round(cn0, 2),
            'CN_db': round(cn, 2),
            'G_over_T': round(GoT, 2),
            'snr_linear': max(10 ** (cn / 10), 1e-6),
            'link_margin_db': round(cn - 10.0, 2),  # giả định ngưỡng 10dB
            'link_ok': cn >= 10.0,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Beamforming: steering vector, pattern, các thuật toán weights
# ══════════════════════════════════════════════════════════════════════════════

def sv(theta_deg: float, N: int, d: float = 0.5) -> np.ndarray:
    """
    Steering vector cho mảng đều (ULA).
    theta_deg: góc so với boresight (độ)
    N: số phần tử
    d: khoảng cách giữa các phần tử (bước sóng)
    """
    n = np.arange(N)
    return np.exp(1j * 2 * np.pi * d * n * np.sin(np.deg2rad(theta_deg)))


def pattern_db(angles: np.ndarray, w: np.ndarray, N: int) -> np.ndarray:
    """
    Tính độ lợi bức xạ (dB) theo các góc.
    angles: mảng góc (độ)
    w: vector trọng số beamforming (complex)
    N: số phần tử (chỉ để tạo steering vector)
    """
    af = np.array([np.dot(w.conj(), sv(a, N)) for a in angles])
    mag = np.maximum(np.abs(af), 1e-12)
    return 20 * np.log10(mag / mag.max())


def w_conv(N: int, t0: float) -> np.ndarray:
    """Conventional beamforming (delay-and-sum)."""
    return sv(t0, N).conj() / N


def w_mvdr(N: int, t0: float, tj: float, snr_db: float) -> np.ndarray:
    """
    MVDR (Minimum Variance Distortionless Response).
    t0: góc chính, tj: góc nhiễu, snr_db: SNR (dB) dùng để ước lượng noise.
    """
    a0 = sv(t0, N)
    aj = sv(tj, N)
    sn = 10 ** (-snr_db / 20)
    # Ma trận hiệp phương sai lý thuyết: tín hiệu + nhiễu + noise
    R = np.outer(a0, a0.conj()) + 20 ** 2 * np.outer(aj, aj.conj()) + sn ** 2 * np.eye(N, dtype=complex)
    R_inv = np.linalg.inv(R + 1e-6 * np.eye(N, dtype=complex))
    w = R_inv @ a0 / (a0.conj() @ R_inv @ a0 + 1e-12)
    return w / (np.linalg.norm(w) + 1e-12)


def w_lms(N: int, t0: float, tj: float, mu: float, snr_db: float,
          n_iter: int = 200) -> np.ndarray:
    """
    LMS (Least Mean Squares) adaptive beamforming.
    mu: bước học.
    """
    a0 = sv(t0, N)
    aj = sv(tj, N)
    sn = 10 ** (-snr_db / 20)
    w = np.zeros(N, dtype=complex)
    for _ in range(n_iter):
        # Tín hiệu tham chiếu là pha ngẫu nhiên (hướng chính mong muốn)
        s = np.exp(1j * 2 * np.pi * np.random.rand())
        # Tổ hợp tín hiệu: tín hiệu mong muốn + nhiễu + tạp âm
        x = a0 * s + aj * 0.5 * np.exp(1j * 2 * np.pi * np.random.rand()) + \
            (np.random.randn(N) + 1j * np.random.randn(N)) * sn / np.sqrt(2)
        e = s - np.dot(w.conj(), x)
        w += mu * np.conj(e) * x
    return w / (np.linalg.norm(w) + 1e-12)


def w_rls(N: int, t0: float, tj: float, snr_db: float,
          lam: float = 0.98, n_iter: int = 200) -> np.ndarray:
    """
    RLS (Recursive Least Squares) adaptive beamforming.
    lam: forgetting factor.
    """
    a0 = sv(t0, N)
    aj = sv(tj, N)
    sn = 10 ** (-snr_db / 20)
    w = np.zeros(N, dtype=complex)
    P = 100.0 * np.eye(N, dtype=complex)
    for _ in range(n_iter):
        s = np.exp(1j * 2 * np.pi * np.random.rand())
        x = a0 * s + aj * 0.5 * np.exp(1j * 2 * np.pi * np.random.rand()) + \
            (np.random.randn(N) + 1j * np.random.randn(N)) * sn / np.sqrt(2)
        Px = P @ x
        k = Px / (lam + x.conj() @ Px)
        e = s - np.dot(w.conj(), x)
        w += k * np.conj(e)
        P = (P - np.outer(k, x.conj() @ P)) / lam
    return w / (np.linalg.norm(w) + 1e-12)


def get_weights(algo: str, N: int, theta0: float, theta_j: float,
                mu: float, snr_db: float) -> np.ndarray:
    """
    Hàm chọn thuật toán beamforming.
    algo: 'conv', 'mvdr', 'lms', 'rls'
    theta0: hướng chính (độ)
    theta_j: hướng nhiễu (độ)
    mu: hệ số học (LMS)
    snr_db: SNR dùng cho MVDR/LMS/RLS
    """
    algo = algo.lower()
    if algo == 'conv':
        return w_conv(N, theta0)
    elif algo == 'mvdr':
        return w_mvdr(N, theta0, theta_j, snr_db)
    elif algo == 'lms':
        return w_lms(N, theta0, theta_j, mu, snr_db)
    elif algo == 'rls':
        return w_rls(N, theta0, theta_j, snr_db)
    else:
        # fallback
        return w_conv(N, theta0)