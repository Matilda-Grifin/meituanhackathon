from __future__ import annotations

import json
from typing import Any

import redis

from lifecare.config import get_settings


def get_redis() -> redis.Redis | None:
    url = get_settings().redis_url
    if not url:
        return None
    return redis.Redis.from_url(url, decode_responses=True)


def cache_get_json(key: str) -> Any | None:
    r = get_redis()
    if not r:
        return None
    try:
        raw = r.get(key)
    except redis.RedisError:
        # Redis 未启动或不可达：降级为无缓存，勿让整个工具失败
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    r = get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
    except redis.RedisError:
        return
