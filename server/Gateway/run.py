#!/usr/bin/env python3
"""
Entry point cho VNU-LEO Tầng 2.

Chế độ 1 — Web server (có WebSocket cho SvelteKit):
    python run.py server

Chế độ 2 — Standalone simulation (chỉ cần terminal):
    python run.py sim [--users 3] [--duration 30]
"""
import sys
import asyncio

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "sim"

    if mode == "server":
        import uvicorn
        print("🚀 Khởi động VNU-LEO Gateway API...")
        print("   REST: http://localhost:8000")
        print("   WS:   ws://localhost:8000/ws")
        print("   Docs: http://localhost:8000/docs\n")
        uvicorn.run(
            "Gateway.server:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
        )
    else:
        n_users  = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        duration = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        try:
            from .handover_engine import run_simulation
        except ImportError:
            from Gateway.handover_engine import run_simulation
        asyncio.run(run_simulation(n_users=n_users, duration_s=duration))

if __name__ == "__main__":
    main()
