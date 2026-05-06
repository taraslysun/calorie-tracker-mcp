"""CLI entrypoint: `python -m mcp_server [--stdio | --http]`."""
from __future__ import annotations

import argparse

from .server import build_server


def main() -> None:
    ap = argparse.ArgumentParser(prog="mcp_server")
    ap.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="streamable-http",
        help="MCP transport (default: streamable-http)",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3000)
    args = ap.parse_args()

    mcp = build_server()
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
