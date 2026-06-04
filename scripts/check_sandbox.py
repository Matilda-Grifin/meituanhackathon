#!/usr/bin/env python3
"""本机沙盒自检：默认 http://127.0.0.1:9000。失败退出码 1，便于 CI / 答辩前一键检查。"""

from __future__ import annotations

import os
import sys

import httpx


def main() -> int:
    base = os.environ.get("MOCK_SANDBOX_BASE_URL", "http://127.0.0.1:9000").rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            h = client.get(f"{base}/health")
            h.raise_for_status()
            body = h.json()
            if body.get("service") != "lifecare-sandbox":
                print("FAIL: /health JSON 不含 lifecare-sandbox:", body)
                return 1
            c = client.get(f"{base}/v1/attraction/smoke_test_id/crowd")
            c.raise_for_status()
            crow = c.json()
            if not crow.get("open", True) and "attraction_id" not in crow:
                print("FAIL: crowd 响应异常:", crow)
                return 1
    except Exception as e:
        print("FAIL:", e)
        print("提示: 先运行 uvicorn sandbox.main:app --host 127.0.0.1 --port 9000")
        return 1
    print("OK:", base, "health + crowd")
    return 0


if __name__ == "__main__":
    sys.exit(main())
