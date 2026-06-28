#!/usr/bin/env node
/**
 * LifeCare 费用看板：静态 UI + /api/stats?mode=online|eval
 */
const fs = require("fs");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

const ROOT = __dirname;
const WS =
  process.env.OPENCLAW_WORKSPACE ||
  path.join(process.env.HOME || "", ".openclaw", "workspace");
const REPO = process.env.LIFECARE_REPO || path.join(WS, "..", "meituan-lifecare-agent");
const PORT = Number(process.env.USAGE_DASHBOARD_PORT || 8849);
const TOKEN = process.env.USAGE_DASHBOARD_TOKEN || "";
const COLLECT_INTERVAL_MS = Number(process.env.USAGE_COLLECT_INTERVAL_MS || 0);
const COLLECTOR = path.join(REPO, "scripts", "usage-collector.py");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".ico": "image/x-icon",
};

let collecting = false;
let lastCollectError = null;

function statsFile(mode) {
  const name = mode === "eval" ? "usage-stats-eval.json" : "usage-stats-online.json";
  return path.join(WS, "logs", name);
}

function runCollector(mode) {
  if (collecting || !fs.existsSync(COLLECTOR)) return;
  collecting = true;
  const py = process.env.PYTHON || "python3";
  const child = spawn(py, [COLLECTOR, "--mode", mode === "eval" ? "eval" : mode === "online" ? "online" : "all"], {
    env: {
      ...process.env,
      OPENCLAW_HOME: path.dirname(WS),
      OPENCLAW_WORKSPACE: WS,
      LIFECARE_REPO: REPO,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => {
    err += d.toString();
  });
  child.on("close", (code) => {
    collecting = false;
    lastCollectError = code === 0 ? null : err || `exit ${code}`;
  });
}

function authOk(req, url) {
  if (!TOKEN) return true;
  const q = url.searchParams.get("token");
  const h = req.headers.authorization || "";
  return q === TOKEN || h === `Bearer ${TOKEN}`;
}

function isPublicStatic(pathname) {
  return /\.(js|css|ico|map)$/i.test(pathname);
}

function readStats(mode) {
  const fp = statsFile(mode);
  if (!fs.existsSync(fp)) return null;
  try {
    return JSON.parse(fs.readFileSync(fp, "utf8"));
  } catch {
    return null;
  }
}

function send(res, code, body, type = "application/json") {
  res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store" });
  res.end(body);
}

function serveStatic(req, res, rel) {
  const safe = path.normalize(rel).replace(/^(\.\.(\/|\\|$))+/, "");
  const fp = path.join(ROOT, safe);
  if (!fp.startsWith(ROOT)) return send(res, 403, "Forbidden");
  if (!fs.existsSync(fp) || fs.statSync(fp).isDirectory()) return send(res, 404, "Not found");
  const ext = path.extname(fp);
  const data = fs.readFileSync(fp);
  res.writeHead(200, {
    "Content-Type": MIME[ext] || "application/octet-stream",
    "Cache-Control": ext === ".html" ? "no-store" : "public, max-age=60",
  });
  res.end(data);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || "/", `http://127.0.0.1:${PORT}`);
  const mode = url.searchParams.get("mode") === "eval" ? "eval" : "online";

  if (url.pathname === "/api/health") {
    return send(
      res,
      200,
      JSON.stringify({
        ok: true,
        collecting,
        lastCollectError,
        mode,
        updatedAt: readStats(mode)?.updatedAt || null,
      })
    );
  }

  if (url.pathname === "/api/stats") {
    if (!authOk(req, url)) return send(res, 401, JSON.stringify({ error: "unauthorized" }));
    const stats = readStats(mode);
    if (!stats) {
      runCollector(mode);
      return send(res, 503, JSON.stringify({ error: "stats not ready", collecting: true, mode }));
    }
    return send(res, 200, JSON.stringify(stats));
  }

  if (url.pathname === "/api/collect" && req.method === "POST") {
    if (!authOk(req, url)) return send(res, 401, JSON.stringify({ error: "unauthorized" }));
    runCollector(url.searchParams.get("mode") || "all");
    return send(res, 202, JSON.stringify({ ok: true, collecting: true }));
  }

  let rel = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
  if (isPublicStatic(url.pathname)) return serveStatic(req, res, rel);
  if ((url.pathname === "/" || url.pathname.endsWith(".html")) && !authOk(req, url)) {
    const login = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>费用看板</title></head>
<body style="font-family:sans-serif;padding:2rem;background:#0f1419;color:#e7ecf3">
<h1>现在就出发 · 费用看板</h1>
<p>请在 URL 加上 <code>?token=你的密钥</code>。</p>
</body></html>`;
    return send(res, 401, login, "text/html; charset=utf-8");
  }
  return serveStatic(req, res, rel);
});

if (COLLECT_INTERVAL_MS > 0) {
  runCollector("all");
  setInterval(() => runCollector("all"), COLLECT_INTERVAL_MS);
}

server.listen(PORT, "0.0.0.0", () => {
  console.error(`lifecare usage-dashboard http://0.0.0.0:${PORT}/`);
});
