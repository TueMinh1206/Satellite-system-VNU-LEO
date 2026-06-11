
from __future__ import annotations

import math
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from anten import LinkBudget, get_weights, pattern_db



lb = LinkBudget()

ANGLES = np.linspace(-90, 90, 181)



@asynccontextmanager
async def lifespan(app: FastAPI):
    print("  [OK] Antenna service started (no handover engine)")
    yield
    print("  [INFO] Server shutting down")


app = FastAPI(title="VNU-LEO Antenna Bridge", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════════════
# REST — Phased Array (anten.py)
# ═════════════════════════════════════════════════════════════════════

def convert_numpy_to_python(obj):

    if isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_to_python(i) for i in obj]
    return obj


@app.get("/api/phased-array")
def get_phased_array(
    el: float = 45.0,
    az: float = 180.0,
    rain: float = 20.0,
):
    """
    Tính toán pattern mảng pha và link budget.
    - el: elevation angle (độ)
    - az: azimuth angle (độ) – chỉ để hiển thị, không dùng trong tính toán hiện tại
    - rain: cường độ mưa (mm/h)
    """
    N = 8                     # số phần tử cố định
    algo = "mvdr"             # thuật toán cố định
    alt_m = 550_000
    el_rad = math.radians(max(el, 1.0))
    range_m = alt_m / math.sin(el_rad)

    # Link budget
    budget = lb.compute(range_m, el, rain_mmh=rain)

    theta0 = 90.0 - el
    theta_j = theta0 + 25.0
    snr = max(budget["CN_db"], 3.0)

    # Beamforming weights và pattern
    w = get_weights(algo, N, theta0, theta_j, 0.05, snr)
    pat = pattern_db(ANGLES, w, N)

    phases = (np.angle(w) * 180 / np.pi).tolist()
    amps = np.abs(w)
    amps = (amps / (amps.max() + 1e-12)).tolist()

    # Chuẩn bị response, chuyển đổi numpy types
    result = {
        "angles": ANGLES.tolist(),
        "pattern": pat.tolist(),
        "phases": phases,
        "amplitudes": amps,
        "budget": convert_numpy_to_python(budget),
        "params": {
            "elevation": el,
            "azimuth": az,
            "N": N,
            "algo": algo,
            "range_km": round(range_m / 1000, 1),
            "theta0": round(theta0, 2),
            "theta_j": round(theta_j, 2),
        },
    }
    return result


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "antenna",
        "time": time.strftime("%H:%M:%S"),
    }
