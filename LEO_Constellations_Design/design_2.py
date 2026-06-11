import numpy as np
import math

R_earth = 6371.0
mu = 398600.4418
h = 800
a = R_earth + h
elev_min = 20.0
omega_e = 360.0 / 86164.0

period = 2 * math.pi * math.sqrt(a**3 / mu)
n = 2 * math.pi / period
mean_motion_rev_per_day = 86400.0 / period

def kepler_position(t, raan, inc, m0):
    M = m0 + n * t
    theta = M
    r_pf = a * np.array([math.cos(theta), math.sin(theta), 0.0])
    cos_raan = math.cos(raan)
    sin_raan = math.sin(raan)
    cos_inc = math.cos(inc)
    sin_inc = math.sin(inc)
    R = np.array([
        [cos_raan, -sin_raan * cos_inc,  sin_raan * sin_inc],
        [sin_raan,  cos_raan * cos_inc, -cos_raan * sin_inc],
        [0.0,       sin_inc,             cos_inc]
    ])
    return R @ r_pf

def station_position(lat_deg, lon_deg, t):
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg + omega_e * t)
    cos_lat = math.cos(lat_rad)
    sin_lat = math.sin(lat_rad)
    return R_earth * np.array([
        cos_lat * math.cos(lon_rad),
        cos_lat * math.sin(lon_rad),
        sin_lat
    ])

def elevation_angle(sat_pos, sta_pos):
    rho = sat_pos - sta_pos
    dot = np.dot(sta_pos, rho)
    norm_sta = np.linalg.norm(sta_pos)
    norm_rho = np.linalg.norm(rho)
    if norm_rho == 0:
        return -90.0
    cos_zenith = dot / (norm_sta * norm_rho)
    cos_zenith = np.clip(cos_zenith, -1.0, 1.0)
    return 90.0 - math.degrees(math.acos(cos_zenith))

# Tạo lưới toàn bộ Việt Nam (bước 0.5°)
latitudes = np.arange(8, 24.5, 2)
longitudes = np.arange(102, 110.5, 2)
stations = {}
idx = 0
for lat in latitudes:
    for lon in longitudes:
        stations[f"p{idx}"] = (lat, lon)
        idx += 1
print(f"Tổng số điểm khảo sát: {len(stations)}")

def simulate(T, P, inc_deg, duration_h=24, step_min=2):
    inc = math.radians(inc_deg)
    sats_per_plane = T // P
    raans = [2 * math.pi * i / P for i in range(P)]
    m0s = [2 * math.pi * j / sats_per_plane for j in range(sats_per_plane)]
    sats = [(raan, inc, m0) for raan in raans for m0 in m0s]
    
    start_t = 0.0
    end_t = duration_h * 3600.0
    step = step_min * 60.0
    times = np.arange(start_t, end_t + step, step)
    
    all_percents = []
    for (lat, lon) in stations.values():
        covered = []
        for t in times:
            sta_pos = station_position(lat, lon, t)
            max_elev = -90.0
            for raan, inc_sat, m0 in sats:
                sat_pos = kepler_position(t, raan, inc_sat, m0)
                elev = elevation_angle(sat_pos, sta_pos)
                if elev > max_elev:
                    max_elev = elev
            covered.append(max_elev >= elev_min)
        percent = 100.0 * sum(covered) / len(covered)
        all_percents.append(percent)
    worst_percent = min(all_percents)
    return worst_percent

def generate_tle_file(T, P, inc_deg, filename="constellation_tle.txt"):
    """Tạo file TLE đúng định dạng: mỗi vệ tinh có dòng tên + 2 dòng TLE"""
    sats_per_plane = T // P
    raans_deg = [360.0 * i / P for i in range(P)]
    m0s_deg = [360.0 * j / sats_per_plane for j in range(sats_per_plane)]
    # Epoch: 26001.50000000 (ngày 01/01/2026 12:00 UTC) như mẫu
    epoch_str = "26001.50000000"
    with open(filename, 'w') as f:
        sat_num = 1
        for raan in raans_deg:
            for m0 in m0s_deg:
                # Dòng tên vệ tinh
                f.write(f"VNULEO-{sat_num:04d}\n")
                # Dòng 1 TLE
                line1 = f"1 {sat_num:05d}U {epoch_str}  .00000000  00000-0  00000-0 0  9990"
                # Dòng 2 TLE: độ nghiêng, RAAN, ecc=0, arg perigee=0, mean anomaly, mean motion, revolution number
                # Revolution number có thể tăng dần (10,20,...) hoặc để 0
                rev_num = sat_num * 10  # tạo số riêng, không quan trọng
                line2 = (f"2 {sat_num:05d} {inc_deg:8.4f} {raan:8.4f} 0000000   0.0000 {m0:8.4f} "
                         f"{mean_motion_rev_per_day:11.8f} {rev_num:5d}")
                f.write(line1 + "\n")
                f.write(line2 + "\n")
                sat_num += 1
    print(f"Đã xuất {T} bộ TLE (3 dòng/vệ tinh) vào file '{filename}'")

def optimize():
    print("Tìm cấu hình tối ưu (toàn bộ lưới Việt Nam >=95% phủ sóng)...")
    for T in range(60, 62, 2):
        divisors = [p for p in range(6, T//2+1) if T % p == 0]
        if not divisors:
            continue
        for P in divisors:
            for inc in range(20, 30, 1):
                print(f"Thử T={T}, P={P}, i={inc}° ...", end=' ', flush=True)
                worst = simulate(T, P, inc, step_min=2)
                print(f"tỷ lệ tệ nhất = {worst:.2f}%")
                if worst >= 95.0:
                    print(f">>> ĐẠT YÊU CẦU: T={T}, P={P}, i={inc}°")
                    filename = f"vnu_leo_{T}sats_{P}planes_{inc}deg.txt"
                    generate_tle_file(T, P, inc, filename)
                    return T, P, inc, worst
    print("Không tìm thấy cấu hình với T<62. Tăng T.")
    return None

if __name__ == "__main__":
    opt = optimize()
    if opt:
        T, P, inc, worst = opt
        print("\n=== CẤU HÌNH TỐI ƯU ===")
        print(f"Số vệ tinh: {T}")
        print(f"Mặt phẳng: {P} (mỗi mặt phẳng {T//P} vệ tinh)")
        print(f"Độ nghiêng: {inc}°")
        print(f"Tỷ lệ phủ sóng trên toàn lãnh thổ: {worst:.2f}%")
    else:
        print("Tăng số vệ tinh lên")