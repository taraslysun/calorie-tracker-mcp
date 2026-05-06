"""Run the AS standalone:
    uv run python -m auth_server [--host 0.0.0.0 --port 3000]
"""
from __future__ import annotations

import argparse

import uvicorn

from .app import build_app


def main() -> None:
    ap = argparse.ArgumentParser(prog="auth_server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3000)
    args = ap.parse_args()
    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
