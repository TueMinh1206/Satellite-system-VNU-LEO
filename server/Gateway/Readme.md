# Cấu trúc chương trình 
Gateway/
├── entities.py              — Models Gateway, Satellite, UserSession, TelemetryFrame
├── physics.py               — Core Haversine, Friis, ITU-R P.618, SGP4, Walker
├── handover_engine.py       — Core Monitor loop, Predictive HO, Make-before-break
├── api/server.py            — FastAPI + WebSocket broadcast
└── run.py                   — Entry point (server / sim)

## Cách chạy chương trình 
Cài thư viện
python 

Chế độ 1 — chỉ test thuật toán (không cần browser)
python run.py sim 3 30        # 3 users, 30 giây

Chế độ 2 — web server cho SvelteKit kết nối
python run.py server
 → REST: http://localhost:8000/docs
 → WS:   ws://localhost:8000/ws