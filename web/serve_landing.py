#!/usr/bin/env python3
"""
在本机或 ECS 上单独起一个静态 HTTP 服务，只托管当前 web/ 目录。
默认 127.0.0.1:8765，与 OpenClaw 18789 及其他项目端口隔离。

用法:
  python serve_landing.py
  python serve_landing.py --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import argparse
import http.server
import os
import socketserver
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve web/ on a dedicated port")
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    args = parser.parse_args()

    os.chdir(WEB_DIR)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as httpd:
        print(f"Serving {WEB_DIR} at http://{args.host}:{args.port}/")
        print("Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
