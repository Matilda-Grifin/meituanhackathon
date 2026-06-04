#!/usr/bin/env python3
"""
本机 MCP 场景回归：直接调用 lifecare 客户端（不经 OpenClaw）。

用法（在 meituan-lifecare-agent 根目录）:
  python benchmark/run_mcp_benchmark.py
  python benchmark/run_mcp_benchmark.py --scenarios benchmark/scenarios.json --out benchmark/results
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BENCH = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 加载 .env：本目录与上级 hackathon 根目录
try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    load_dotenv(_ROOT.parent / ".env")
except ImportError:
    pass

from lifecare.clients import amap as amap_client
from lifecare.clients import weather as weather_client
from lifecare.config import get_settings


def _load_scenarios(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("scenarios file must be a JSON array")
    return data


def _check_search(sc: dict, data: dict) -> tuple[bool, str]:
    ex = sc.get("expect") or {}
    min_pois = int(ex.get("min_pois", 1))
    allow_zero = bool(ex.get("allow_zero_pois", False))
    need_rep = bool(ex.get("each_poi_must_have_reputation", True))
    max_ms = int(ex.get("max_latency_ms", 30_000))

    if not isinstance(data, dict):
        return False, "response is not a dict"

    if "ok" not in data:
        return False, "missing ok field"

    if not data.get("ok"):
        if allow_zero and min_pois == 0:
            return True, "zero-result scenario: ok=false or empty is acceptable"
        return False, f"search ok=false: {data.get('error')}"

    pois = data.get("pois") or []
    if len(pois) < min_pois:
        return False, f"want min_pois={min_pois}, got {len(pois)}"

    for i, p in enumerate(pois):
        if need_rep:
            rep = p.get("reputation")
            if not isinstance(rep, dict):
                return False, f"poi[{i}] missing reputation"
            fw = rep.get("for_weights")
            if not isinstance(fw, dict):
                return False, f"poi[{i}] missing for_weights"
            if sc["search"].get("attach_mock_reputation", True):
                if fw.get("star_for_rank") is None:
                    return False, f"poi[{i}] star_for_rank null with mock on"
        else:
            if "reputation" not in p:
                return False, f"poi[{i}] missing reputation object"

    return True, "search ok"


def _run_weather() -> tuple[bool, str, float]:
    t0 = time.perf_counter()
    settings = get_settings()
    try:
        w = weather_client.fetch_open_meteo(settings.default_lat, settings.default_lng)
    except Exception as e:  # noqa: BLE001
        return False, str(e), (time.perf_counter() - t0) * 1000
    elapsed = (time.perf_counter() - t0) * 1000
    if not isinstance(w, dict) or not w.get("ok", True):
        return False, json.dumps(w, ensure_ascii=False)[:500], elapsed
    return True, "weather ok", elapsed


def _run_route_between_first_two(pois: list[dict]) -> tuple[bool, str, float]:
    coords = []
    for p in pois[:3]:
        loc = p.get("location") or {}
        lng, lat = loc.get("lng"), loc.get("lat")
        if lng is not None and lat is not None:
            coords.append((float(lng), float(lat)))
        if len(coords) >= 2:
            break
    if len(coords) < 2:
        return True, "skip route (<2 coords)", 0.0
    (lng0, lat0), (lng1, lat1) = coords[0], coords[1]
    t0 = time.perf_counter()
    r = amap_client.plan_route_driving(lng0, lat0, lng1, lat1)
    elapsed = (time.perf_counter() - t0) * 1000
    if not r.get("ok"):
        return False, r.get("error", str(r)), elapsed
    return True, f"route distance_m={r.get('distance_m')}", elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=Path, default=_BENCH / "scenarios.json")
    ap.add_argument("--out", type=Path, default=_BENCH / "results")
    ap.add_argument(
        "--only",
        type=str,
        default="",
        help="只跑指定场景 id，逗号分隔，例如: hz_museum,sh_coffee",
    )
    args = ap.parse_args()

    scenarios = _load_scenarios(args.scenarios)
    if args.only.strip():
        allow = {x.strip() for x in args.only.split(",") if x.strip()}
        scenarios = [s for s in scenarios if s.get("id") in allow]
        if not scenarios:
            raise SystemExit(f"--only 未匹配任何场景: {allow}")
    args.out.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(_ROOT),
        "scenarios_file": str(args.scenarios),
        "amap_key_configured": bool(get_settings().amap_key),
        "results": [],
        "summary": {"passed": 0, "failed": 0},
    }

    all_ok = True
    for sc in scenarios:
        sid = sc["id"]
        chain = sc.get("chain") or {}
        search_cfg = sc.get("search") or {}
        t0 = time.perf_counter()
        try:
            data = amap_client.search_poi_text(
                sc["keywords"],
                sc["city"],
                limit=int(search_cfg.get("limit", 8)),
                extensions=str(search_cfg.get("extensions", "all")),
                attach_mock_reputation=bool(search_cfg.get("attach_mock_reputation", True)),
            )
        except Exception as e:  # noqa: BLE001
            all_ok = False
            report["results"].append(
                {
                    "id": sid,
                    "passed": False,
                    "error": repr(e),
                    "latency_search_ms": (time.perf_counter() - t0) * 1000,
                }
            )
            report["summary"]["failed"] += 1
            continue

        search_ms = (time.perf_counter() - t0) * 1000
        ok, msg = _check_search(sc, data)
        detail: dict = {
            "id": sid,
            "description": sc.get("description"),
            "passed": ok,
            "check_message": msg,
            "latency_search_ms": round(search_ms, 2),
            "flags_history_prefs": sc.get("flags_history_prefs"),
            "user_prompt_hint": sc.get("user_prompt_hint"),
        }

        ex = sc.get("expect") or {}
        if ok and search_ms > float(ex.get("max_latency_ms", 1e9)):
            ok = False
            msg = f"latency {search_ms:.0f}ms > max {ex.get('max_latency_ms')}"
            detail["passed"] = False
            detail["check_message"] = msg

        if ok and chain.get("weather"):
            w_ok, w_msg, w_ms = _run_weather()
            detail["weather_ok"] = w_ok
            detail["weather_message"] = w_msg
            detail["latency_weather_ms"] = round(w_ms, 2)
            if not w_ok:
                ok = False
                detail["passed"] = False
                detail["check_message"] = f"weather failed: {w_msg}"

        if ok and chain.get("route_first_two_pois"):
            pois = (data.get("pois") or []) if data.get("ok") else []
            r_ok, r_msg, r_ms = _run_route_between_first_two(pois)
            detail["route_ok"] = r_ok
            detail["route_message"] = r_msg
            detail["latency_route_ms"] = round(r_ms, 2)
            if not r_ok:
                ok = False
                detail["passed"] = False
                detail["check_message"] = f"route failed: {r_msg}"

        if not ok:
            all_ok = False
            report["summary"]["failed"] += 1
        else:
            report["summary"]["passed"] += 1

        detail["passed"] = ok
        report["results"].append(detail)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = args.out / f"report_{ts}.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = args.out / "latest.json"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"written: {out_file}")
    print(f"written: {latest}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
