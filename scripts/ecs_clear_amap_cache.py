#!/usr/bin/env python3
"""Delete lifecare amap poi cache keys (optional pattern)."""
import sys
sys.path.insert(0, "/root/meituan-lifecare-agent")
from lifecare.cache_redis import get_redis

r = get_redis()
if r is None:
    print("no redis")
    sys.exit(0)
n = 0
for key in r.scan_iter("lifecare:amap:poi:*"):
    r.delete(key)
    n += 1
print("deleted", n, "poi cache keys")
