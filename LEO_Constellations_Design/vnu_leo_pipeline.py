
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import json
from skyfield.api import EarthSatellite, load, wgs84
from datetime import datetime, timezone, timedelta

Re     = 6371.0       # km
Re_tle = 6378.137     # km WGS84
mu     = 398600.4418  # km³/s²

VN_LAT_MIN, VN_LAT_MAX = 8.0,  23.5
VN_LON_MIN, VN_LON_MAX = 102.0, 110.0


def coverage_angle(h, alpha_deg):
    """θ = arcsin((h+Re)/Re · sinα) − α   [eq.(2)]"""
    a   = np.radians(alpha_deg)
    arg = min((h + Re) / Re * np.sin(a), 1.0)
    return np.degrees(np.arcsin(arg) - a)

def n2_required(theta_deg, psi_min_deg):
    """n2 ≥ π / arccos(cosθ / cosψ_min)   [eq.(10)]"""
    ct = np.cos(np.radians(theta_deg))
    cp = np.cos(np.radians(psi_min_deg))
    if cp <= 0 or ct / cp > 1.0:
        return 999
    return int(np.ceil(np.pi / np.arccos(ct / cp)))

def soc_polar_sym(h, alpha_deg, n1_range=range(3, 100)):
    """ψ_min = π/(2n1)   [eq.(12)(13)]"""
    theta = coverage_angle(h, alpha_deg)
    best  = {"N": float("inf")}
    for n1 in n1_range:
        psi_deg = np.degrees(np.pi / (2 * n1))
        if theta <= psi_deg:
            continue
        n2 = n2_required(theta, psi_deg)
        N  = n1 * n2
        if N < best["N"]:
            best = {"N": N, "n1": n1, "n2": n2, "psi_min": psi_deg, "theta": theta}
    return best

def soc_polar_nonsym(h, alpha_deg, n1_range=range(3, 100)):
    """
    ψ_min = (n1−1)/(n1+1) · θ   [eq.(17) — sửa từ v1]
    Điều kiện tồn tại: n1 > π/(2θ)  [từ eq.(16)]
    """
    theta     = coverage_angle(h, alpha_deg)
    theta_rad = np.radians(theta)
    best      = {"N": float("inf")}
    for n1 in n1_range:
        if n1 * theta_rad <= np.pi / 2:
            continue
        psi_rad = (n1 - 1) / (n1 + 1) * theta_rad
        psi_deg = np.degrees(psi_rad)
        if theta <= psi_deg:
            continue
        n2 = n2_required(theta, psi_deg)
        N  = n1 * n2
        if N < best["N"]:
            best = {"N": N, "n1": n1, "n2": n2, "psi_min": psi_deg, "theta": theta}
    return best

def soc_inclined_vn(h, alpha_deg, phi_max_deg=VN_LAT_MAX,
                    n1_range=range(10, 70)):
    theta = coverage_angle(h, alpha_deg)
    best  = {"N": float("inf")}

    for i_deg in np.arange(phi_max_deg + 1, 86, 1.0):
        i        = np.radians(i_deg)
        phi_max  = np.radians(phi_max_deg)

        for n1 in n1_range:
            phi_j = [np.arctan(np.tan(i) * np.cos(j * np.pi / n1))
                     for j in range(1, n1)]
            phi_1_deg = np.degrees(phi_j[0]) if phi_j else i_deg

            psi_mesh = []
            for m in range(1, n1):
                mpi_n1 = m  * np.pi / n1
                pi_n1  = np.pi / n1
                num = np.sin(mpi_n1) * np.sin(pi_n1) * np.tan(i)
                den = 1 + (np.cos(mpi_n1) * np.cos(pi_n1) *
                           np.cos((m - 1) * pi_n1) * np.tan(i)**2)
                if abs(den) < 1e-12:
                    continue
                X_U  = np.arctan(num / den)
                pm1  = phi_j[m - 2] if m >= 2 else i
                sp   = np.clip(np.sin(X_U) * np.cos(i) / np.cos(pm1), -1, 1)
                psi_mesh.append(np.degrees(np.arcsin(sp)))

            if phi_max_deg > phi_1_deg:
                term    = (np.sin(phi_max) * np.cos(i) -
                           np.cos(phi_max) * np.sin(i) * np.cos(np.pi / n1))
                psi_ext = np.degrees(np.arcsin(np.clip(term, -1, 1)))
                psi_min = max(max(psi_mesh) if psi_mesh else 0, psi_ext)
            else:
                psi_min = max(psi_mesh) if psi_mesh else 0

            if theta <= psi_min:
                continue
            n2 = n2_required(theta, psi_min)
            N  = n1 * n2
            if N < best["N"]:
                best = {"N": N, "n1": n1, "n2": n2,
                        "i": i_deg, "psi_min": psi_min, "theta": theta}
    return best

# ═══════════════════════════════════════════════════════════
# PHẦN 2 — TÌM ALTITUDE TỐI ƯU (sweep)
# ═══════════════════════════════════════════════════════════

def latency_ms(h_km):
    """One-way propagation latency (ms), xấp xỉ."""
    return round(2 * h_km / 300, 1)

# Tiêu chí VoIP: latency < 150 ms (ITU-T G.114)
VOIP_MAX_LATENCY_MS = 150.0
# Tiêu chí Radar: revisit ≤ 2h = 120 min
RADAR_MAX_REVISIT_MIN = 120.0

def orbit_period_min(h_km):
    a = (Re + h_km) * 1e3   # m
    return 2 * np.pi * np.sqrt(a**3 / 3.986e14) / 60.0

def revisit_time_min(n1, h_km):
    """
    Ước tính thời gian revisit đơn giản:
    T_revisit ≈ T_orbit / n1
    (mỗi mặt phẳng quỹ đạo thêm 1 lần phủ / chu kỳ)
    """
    return orbit_period_min(h_km) / n1

def sweep_altitude(alpha_deg=32, altitudes=None):
    """
    Quét altitude từ 400–1500 km, với α cố định.
    Trả về bảng kết quả để vẽ và chọn điểm tối ưu.
    """
    if altitudes is None:
        altitudes = list(range(400, 1600, 100))

    rows = []
    for h in altitudes:
        r_ns  = soc_polar_nonsym(h, alpha_deg)
        r_sym = soc_polar_sym(h, alpha_deg)
        r_inc = soc_inclined_vn(h, alpha_deg)
        lat   = latency_ms(h)
        T_orb = orbit_period_min(h)
        rev   = revisit_time_min(r_ns.get("n1", 1), h)
        rows.append({
            "h":         h,
            "theta":     r_ns.get("theta", 0),
            "latency_ms": lat,
            "T_orbit_min": round(T_orb, 1),
            "revisit_min": round(rev, 1),
            "voip_ok":   lat <= VOIP_MAX_LATENCY_MS,
            "radar_ok":  rev <= RADAR_MAX_REVISIT_MIN,
            "both_ok":   (lat <= VOIP_MAX_LATENCY_MS) and (rev <= RADAR_MAX_REVISIT_MIN),
            "nonsym":    r_ns,
            "sym":       r_sym,
            "inclined":  r_inc,
        })
    return rows

def pick_optimal(rows):
    """
    Từ bảng sweep, chọn altitude tối ưu:
    - both_ok = True (thỏa cả VoIP lẫn Radar)
    - Trong đó minimize N (non-sym polar)
    """
    candidates = [r for r in rows if r["both_ok"] and r["nonsym"].get("N", 9999) < 9999]
    if not candidates:
        # Nới lỏng: chỉ cần voip_ok
        candidates = [r for r in rows if r["voip_ok"] and r["nonsym"].get("N", 9999) < 9999]
    if not candidates:
        candidates = rows
    return min(candidates, key=lambda r: r["nonsym"].get("N", 9999))

# ═══════════════════════════════════════════════════════════
# PHẦN 3 — TLE GENERATOR
# ═══════════════════════════════════════════════════════════

def make_tle(sid, i_deg, raan_deg, nu_deg, h_km):
    a = Re_tle + h_km
    n = np.sqrt(mu / a**3) * 86400 / (2 * np.pi)
    l1 = (f"1 {sid:05d}U 26001A   26001.50000000"
          f"  .00000000  00000-0  00000-0 0  9990")
    l2 = (f"2 {sid:05d} {i_deg:08.4f} {raan_deg % 360:08.4f}"
          f" 0000001 000.0000 {nu_deg % 360:08.4f} {n:011.8f}{sid:5d}0")
    return f"VNULEO-{sid:04d}", l1, l2

def build_constellation_tle(n1, n2, h_km, i_deg=90.0, nonsym=True):
    """
    Sinh TLE cho chòm sao polar.
    nonsym=True: áp phase seam đúng theo bài báo mục 3.3.2.
    """
    sats = []
    sid  = 1
    for k in range(n1):
        raan = k * 180.0 / n1   # ascending nodes ∈ [0, π)
        # Phase offset cho counter-rotating seam (mặt phẳng cuối)
        if nonsym and k == n1 - 1:
            # Δ_2 = 2ψ → lệch nửa khoảng cách vệ tinh
            phase = 180.0 / n2
        else:
            phase = 0.0
        for j in range(n2):
            nu = j * 360.0 / n2 + phase
            sats.append(make_tle(sid, i_deg, raan, nu, h_km))
            sid += 1
    return sats
def get_positions(tle_list, ts, t):
    pos = []
    for name, l1, l2 in tle_list:
        sp = wgs84.subpoint(EarthSatellite(l1, l2, name, ts).at(t))
        pos.append((sp.latitude.degrees, sp.longitude.degrees, sp.elevation.km))
    return pos

def check_coverage_vn(positions, theta_deg, lats, lons):
    lats_r = np.radians(lats[:, None])
    lons_r = np.radians(lons[None, :])
    covered = np.zeros((len(lats), len(lons)), dtype=bool)
    for slat, slon, sh in positions:
        th_actual = coverage_angle(sh, np.degrees(
            np.arcsin(np.clip(Re / (Re + sh) * np.sin(np.radians(theta_deg)), 0, 1))
        )) if sh > 0 else theta_deg
        slr  = np.radians(slat)
        slnr = np.radians(slon)
        cos_a = (np.sin(slr) * np.sin(lats_r) +
                 np.cos(slr) * np.cos(lats_r) * np.cos(lons_r - slnr))
        covered |= (np.degrees(np.arccos(np.clip(cos_a, -1, 1))) <= theta_deg)
    return covered

def verify_vn(tle_list, theta_deg, h_km, n_steps=24):

    T_min  = orbit_period_min(h_km)
    dt_min = T_min / n_steps
    t0     = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    times  = [t0 + timedelta(minutes=i * dt_min) for i in range(n_steps)]

    lats = np.arange(VN_LAT_MIN, VN_LAT_MAX + 0.5, 0.5)
    lons = np.arange(VN_LON_MIN, VN_LON_MAX + 0.5, 0.5)

    ts       = load.timescale()
    coverage = []
    for t in times:
        st  = ts.from_datetime(t)
        pos = get_positions(tle_list, ts, st)
        cov = check_coverage_vn(pos, theta_deg, lats, lons)
        coverage.append(cov)

    timeline = [c.mean() * 100 for c in coverage]

    # Revisit time thực tế: thời gian dài nhất một điểm không được phủ
    # Đơn giản hóa: thời gian liên tục < 100% coverage
    gaps = [dt_min for c in timeline if c < 99.0]
    revisit_actual = sum(gaps) / max(len(gaps), 1) if gaps else 0.0

    return {
        "avg_pct":       round(float(np.mean(timeline)), 1),
        "min_pct":       round(float(np.min(timeline)),  1),
        "full_pct":      round(sum(1 for c in timeline if c >= 99.0) / n_steps * 100, 0),
        "revisit_min":   round(revisit_actual, 1),
        "T_orbit_min":   round(T_min, 1),
        "timeline":      [round(v, 1) for v in timeline],
        "dt_min":        round(dt_min, 2),
    }

# ═══════════════════════════════════════════════════════════
# PHẦN 5 — VẼ KẾT QUẢ
# ═══════════════════════════════════════════════════════════

BG = "#07090f"
S1 = "#0d1520"
C1 = "#00e5ff"
C2 = "#ff5f40"
C3 = "#7cfc00"
CG = "#aabbcc"

def plot_all(sweep_rows, optimal, verif, out_prefix="vnu_leo"):
    fig = plt.figure(figsize=(18, 11), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig,
                            hspace=0.42, wspace=0.38,
                            left=0.07, right=0.96,
                            top=0.88, bottom=0.10)

    # ── Panel 1: N vs altitude ──────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    hs  = [r["h"] for r in sweep_rows]
    Ns  = [r["nonsym"].get("N", np.nan) for r in sweep_rows]
    Ns2 = [r["sym"].get("N", np.nan)    for r in sweep_rows]
    Ni  = [r["inclined"].get("N", np.nan) for r in sweep_rows]
    ax1.plot(hs, Ns,  color=C1, lw=2,   label="Non-sym polar ★")
    ax1.plot(hs, Ns2, color=C2, lw=1.5, ls="--", label="Sym polar")
    ax1.plot(hs, Ni,  color=CG, lw=1.5, ls=":",  label="Inclined")
    ax1.axvline(optimal["h"], color="yellow", lw=1.2, ls="--", alpha=0.7)
    ax1.set_facecolor(S1); ax1.set_title("Số vệ tinh N vs Altitude", color="white", fontsize=9)
    ax1.set_xlabel("h (km)", color=CG, fontsize=8)
    ax1.set_ylabel("N", color=CG, fontsize=8)
    ax1.tick_params(colors=CG, labelsize=7)
    ax1.legend(fontsize=7, labelcolor="white", facecolor=S1, edgecolor=S1)
    for sp in ax1.spines.values(): sp.set_edgecolor("#1a2840")

    # ── Panel 2: Latency & Revisit vs altitude ──────────────
    ax2 = fig.add_subplot(gs[0, 1])
    lats_v = [r["latency_ms"]  for r in sweep_rows]
    revs_v = [r["revisit_min"] for r in sweep_rows]
    ax2.plot(hs, lats_v, color=C1, lw=2, label="Latency (ms)")
    ax2b = ax2.twinx()
    ax2b.plot(hs, revs_v, color=C2, lw=2, label="Revisit (min)")
    ax2.axhline(VOIP_MAX_LATENCY_MS,  color=C1, lw=0.8, ls=":", alpha=0.6)
    ax2b.axhline(RADAR_MAX_REVISIT_MIN, color=C2, lw=0.8, ls=":", alpha=0.6)
    ax2.axvline(optimal["h"], color="yellow", lw=1.2, ls="--", alpha=0.7)
    ax2.set_facecolor(S1); ax2.set_title("Latency & Revisit vs Altitude", color="white", fontsize=9)
    ax2.set_xlabel("h (km)", color=CG, fontsize=8)
    ax2.set_ylabel("Latency (ms)", color=C1, fontsize=8)
    ax2b.set_ylabel("Revisit (min)", color=C2, fontsize=8)
    ax2.tick_params(colors=CG, labelsize=7)
    ax2b.tick_params(colors=CG, labelsize=7)
    lines1, labs1 = ax2.get_legend_handles_labels()
    lines2, labs2 = ax2b.get_legend_handles_labels()
    ax2.legend(lines1+lines2, labs1+labs2, fontsize=7, labelcolor="white",
               facecolor=S1, edgecolor=S1)
    for sp in ax2.spines.values(): sp.set_edgecolor("#1a2840")

    # ── Panel 3: Bar so sánh 3 chòm sao tại altitude tối ưu ─
    ax3 = fig.add_subplot(gs[0, 2])
    h_opt = optimal["h"]
    r_opt = next(r for r in sweep_rows if r["h"] == h_opt)
    labels_bar = ["Inclined", "Polar\nSym", "Polar\nNon-sym★"]
    vals_bar   = [r_opt["inclined"].get("N", 0),
                  r_opt["sym"].get("N", 0),
                  r_opt["nonsym"].get("N", 0)]
    colors_bar = [CG, C2, C1]
    bars = ax3.bar(labels_bar, vals_bar, color=colors_bar,
                   width=0.55, edgecolor=BG, linewidth=0.5)
    for bar, v in zip(bars, vals_bar):
        ax3.text(bar.get_x() + bar.get_width()/2,
                 bar.get_height() + max(vals_bar)*0.02,
                 f"{int(v):,}", ha="center", va="bottom",
                 color="white", fontsize=9, fontweight="bold")
    ax3.set_facecolor(S1)
    ax3.set_title(f"So sánh tại h={h_opt}km (α=32°)", color="white", fontsize=9)
    ax3.set_ylabel("Số vệ tinh N", color=CG, fontsize=8)
    ax3.tick_params(colors=CG, labelsize=8)
    for sp in ax3.spines.values(): sp.set_edgecolor("#1a2840")

    # ── Panel 4: Coverage timeline ──────────────────────────
    ax4 = fig.add_subplot(gs[1, 0])
    tl  = verif["timeline"]
    ts_x = [i * verif["dt_min"] for i in range(len(tl))]
    ax4.fill_between(ts_x, tl, alpha=0.25, color=C1)
    ax4.plot(ts_x, tl, color=C1, lw=2)
    ax4.axhline(99.0, color="yellow", lw=0.8, ls="--", alpha=0.6, label="99%")
    ax4.set_facecolor(S1)
    ax4.set_title("Coverage VN theo thời gian (1 chu kỳ)", color="white", fontsize=9)
    ax4.set_xlabel("Thời gian (phút)", color=CG, fontsize=8)
    ax4.set_ylabel("Coverage (%)", color=CG, fontsize=8)
    ax4.set_ylim(0, 105)
    ax4.tick_params(colors=CG, labelsize=7)
    ax4.legend(fontsize=7, labelcolor="white", facecolor=S1, edgecolor=S1)
    for sp in ax4.spines.values(): sp.set_edgecolor("#1a2840")

    # ── Panel 5: Bản đồ phủ sóng VN ────────────────────────
    ax5 = fig.add_subplot(gs[1, 1:])
    # vẽ placeholder (bản đồ thực cần cartopy; dùng lưới đơn giản)
    lats_g = np.arange(VN_LAT_MIN, VN_LAT_MAX + 0.5, 0.5)
    lons_g = np.arange(VN_LON_MIN, VN_LON_MAX + 0.5, 0.5)
    # Tải coverage snapshot từ verif nếu có
    if "snapshot" in verif:
        cov_map = verif["snapshot"]
        lg, la = np.meshgrid(lons_g, lats_g)
        ax5.contourf(lg, la, cov_map.astype(float),
                     levels=[0.5, 1.5], colors=[C1], alpha=0.4)
        ax5.contour(lg, la, cov_map.astype(float),
                    levels=[0.5], colors=[C1], linewidths=0.8)
    # Khung VN
    ax5.plot([VN_LON_MIN, VN_LON_MAX, VN_LON_MAX, VN_LON_MIN, VN_LON_MIN],
             [VN_LAT_MIN, VN_LAT_MIN, VN_LAT_MAX, VN_LAT_MAX, VN_LAT_MIN],
             "r--", lw=1.5)
    # Lưới
    for lo in np.arange(100, 115, 2): ax5.axvline(lo, color="#1e3050", lw=0.4)
    for la in np.arange(5,  28,  2):  ax5.axhline(la, color="#1e3050", lw=0.4)
    ax5.set_xlim(100, 115); ax5.set_ylim(5, 26)
    ax5.set_facecolor("#0a1828")
    ns = optimal["nonsym"]
    ax5.set_title(
        f"Vùng phủ sóng Việt Nam — h={optimal['h']}km | "
        f"N={ns['N']} ({ns['n1']}×{ns['n2']}) | "
        f"avg={verif['avg_pct']}% | revisit={verif['revisit_min']}min",
        color="white", fontsize=9)
    ax5.set_xlabel("Kinh độ (°E)", color=CG, fontsize=8)
    ax5.set_ylabel("Vĩ độ (°N)", color=CG, fontsize=8)
    ax5.tick_params(colors=CG, labelsize=7)
    for sp in ax5.spines.values(): sp.set_edgecolor("#1a2840")

    fig.suptitle(
        f"VNU-LEO v2 — Tối ưu cho Việt Nam  |  α={32}°  |  "
        f"Altitude tối ưu: {optimal['h']} km",
        color="white", fontsize=12, fontweight="bold")

    out = f"{out_prefix}_dashboard.png"
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  ✓ {out}")
    return out

def main():
    ALPHA_DEG = 32  
    print(f"\n[1/4] Sweep altitude (α={ALPHA_DEG}°)...")
    altitudes  = list(range(400, 1600, 100))
    sweep_rows = sweep_altitude(ALPHA_DEG, altitudes)

    print(f"\n  {'h(km)':>6} {'θ(°)':>6} {'N_ns':>6} {'Lat(ms)':>8} "
          f"{'Rev(min)':>9} {'VoIP':>5} {'Radar':>6}")
    print("  " + "-" * 55)
    for r in sweep_rows:
        ns = r["nonsym"]
        print(f"  {r['h']:>6} {r['theta']:>6.2f} {ns.get('N',0):>6} "
              f"{r['latency_ms']:>8.1f} {r['revisit_min']:>9.1f} "
              f"{'✓' if r['voip_ok'] else '✗':>5} "
              f"{'✓' if r['radar_ok'] else '✗':>6}")

    optimal = pick_optimal(sweep_rows)
    ns_opt  = optimal["nonsym"]
    print(f"\n[2/4] Altitude tối ưu: h = {optimal['h']} km")
    print(f"      θ = {optimal['theta']:.3f}°")
    print(f"      Latency = {optimal['latency_ms']} ms  "
          f"({'✓ VoIP ok' if optimal['voip_ok'] else '✗ quá cao cho VoIP'})")
    print(f"      Revisit ≈ {optimal['revisit_min']} min  "
          f"({'✓ Radar ok' if optimal['radar_ok'] else '✗'})")
    print(f"\n      Non-sym polar: N={ns_opt['N']} "
          f"(n1={ns_opt['n1']} planes × n2={ns_opt['n2']} sats)")
    print(f"      Sym polar    : N={optimal['sym'].get('N','?')}")
    print(f"      Inclined     : N={optimal['inclined'].get('N','?')} "
          f"(i={optimal['inclined'].get('i','?')}°)")

    tle_list = build_constellation_tle(
        ns_opt["n1"], ns_opt["n2"], optimal["h"],
        i_deg=90.0, nonsym=True
    )
    print(f"  Đã sinh {len(tle_list)} TLE")

    verif = verify_vn(tle_list, optimal["theta"], optimal["h"], n_steps=24)
    print(f"  Coverage VN: avg={verif['avg_pct']}%, "
          f"min={verif['min_pct']}%, full={verif['full_pct']}%")
    print(f"  Revisit thực tế: {verif['revisit_min']} min")
    print(f"  Chu kỳ quỹ đạo: {verif['T_orbit_min']} min")

    ts  = load.timescale()
    t0  = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    st  = ts.from_datetime(t0)
    pos = get_positions(tle_list, ts, st)
    lats_g = np.arange(VN_LAT_MIN, VN_LAT_MAX + 0.5, 0.5)
    lons_g = np.arange(VN_LON_MIN, VN_LON_MAX + 0.5, 0.5)
    verif["snapshot"] = check_coverage_vn(pos, optimal["theta"], lats_g, lons_g)

    # ── Bước 4: Lưu kết quả ─────────────────────────────────
    print("\n[4/4] Lưu file...")

    # JSON
    result = {
        "project": "VNU-LEO v2",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "coverage_region": {
            "name": "Vietnam",
            "lat_min": VN_LAT_MIN, "lat_max": VN_LAT_MAX,
            "lon_min": VN_LON_MIN, "lon_max": VN_LON_MAX,
        },
        "alpha_deg":       ALPHA_DEG,
        "optimal_altitude_km": optimal["h"],
        "criteria": {
            "voip_max_latency_ms":    VOIP_MAX_LATENCY_MS,
            "radar_max_revisit_min":  RADAR_MAX_REVISIT_MIN,
        },
        "optimal_constellation": {
            "type":            "non_symmetrical_polar",
            "inclination_deg": 90,
            "n1_planes":       ns_opt["n1"],
            "n2_sats_per_plane": ns_opt["n2"],
            "total_N":         ns_opt["N"],
            "psi_min_deg":     round(ns_opt["psi_min"], 4),
            "theta_deg":       round(optimal["theta"], 4),
            "latency_ms":      optimal["latency_ms"],
            "est_revisit_min": optimal["revisit_min"],
        },
        "verification": {
            "method":          "Skyfield SGP4",
            "grid":            "0.5°×0.5° VN box",
            "n_timesteps":     24,
            "avg_coverage_pct":  verif["avg_pct"],
            "min_coverage_pct":  verif["min_pct"],
            "full_coverage_pct": verif["full_pct"],
            "revisit_min":       verif["revisit_min"],
            "T_orbit_min":       verif["T_orbit_min"],
        },
        "sweep_table": [
            {
                "h": r["h"],
                "theta": round(r["theta"], 3),
                "latency_ms": r["latency_ms"],
                "revisit_min": r["revisit_min"],
                "voip_ok": bool(r["voip_ok"]),
                "radar_ok": bool(r["radar_ok"]),
                "N_nonsym":   r["nonsym"].get("N"),
                "N_sym":      r["sym"].get("N"),
                "N_inclined": r["inclined"].get("N"),
            }
            for r in sweep_rows
        ],
        "reference": "Chen et al. (2017) MATEC Web of Conferences 114, 01012"
    }

    with open("vnu_leo_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("  ✓ vnu_leo_result.json")

    # TLE
    tle_lines = [
    ]
    for name, l1, l2 in tle_list:
        tle_lines += [name, l1, l2]
    with open("constellation_tle.txt", "w") as f:
        f.write("\n".join(tle_lines))
    print("  ✓ constellation_tle.txt")

    plot_all(sweep_rows, optimal, verif)

    print("\n" + "=" * 60)
    print("  KẾT QUẢ TỐI ƯU CHO VIỆT NAM")
    print("=" * 60)
    print(f"  Altitude       : {optimal['h']} km")
    print(f"  Coverage angle : θ = {optimal['theta']:.3f}°")
    print(f"  Latency        : {optimal['latency_ms']} ms  (VoIP ok: {optimal['voip_ok']})")
    print(f"  Revisit (ước)  : {optimal['revisit_min']} min  (Radar ok: {optimal['radar_ok']})")
    print(f"  Chòm sao       : Non-sym polar — N={ns_opt['N']} "
          f"({ns_opt['n1']} planes × {ns_opt['n2']} sats/plane)")
    print(f"  Coverage thực  : avg={verif['avg_pct']}%, min={verif['min_pct']}%")
    print("=" * 60)

if __name__ == "__main__":
    main()