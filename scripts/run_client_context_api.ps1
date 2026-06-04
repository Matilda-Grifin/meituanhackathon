# 本地：为 gateway-chat-ui 提供 /api/client-context（Vite 已代理到 8098）
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (Test-Path ".venv\Scripts\Activate.ps1") { .\.venv\Scripts\Activate.ps1 }
uvicorn gateway_context_api:app --host 127.0.0.1 --port 8098
