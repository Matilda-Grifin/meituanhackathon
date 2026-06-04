#!/usr/bin/env bash
# 通过 Gateway WS 调 sessions.create 在 ECS 上常因 CLI 需设备配对而失败。
# 请改用同目录下的 ecs_seed_main_session.py（直接写入会话库 + 重启 gateway）。

echo "Use: python3 ecs_seed_main_session.py (on the ECS as root)" >&2
exit 1
