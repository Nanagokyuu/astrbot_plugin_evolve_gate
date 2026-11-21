"""Built-in Web Dashboard for EvolveGate (default 127.0.0.1:8557)."""

from __future__ import annotations

import time
from typing import Any

from aiohttp import web

try:
    from .api import EvolveGateAPI
    from .engine import run_evolution_cycle
    from .store import EvolveStore
except ImportError:
    from api import EvolveGateAPI
    from engine import run_evolution_cycle
    from store import EvolveStore


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EvolveGate Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --ok: #34d399;
      --warn: #fbbf24;
      --bad: #f87171;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    .container { max-width: 1080px; margin: 0 auto; }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 24px;
    }
    h1 { margin: 0; font-size: 1.5rem; }
    .subtitle { color: var(--muted); font-size: 0.9rem; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; }
    button {
      background: var(--accent);
      color: #0f172a;
      border: none;
      padding: 8px 14px;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
    }
    button.secondary { background: #334155; color: var(--text); }
    button.danger { background: var(--bad); color: #0f172a; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 20px;
    }
    .metric-label { color: var(--muted); font-size: 0.85rem; }
    .metric-value { font-size: 1.6rem; font-weight: 700; margin-top: 4px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    th { color: var(--muted); font-weight: 600; }
    code {
      background: #0f172a;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.85em;
    }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 600;
    }
    .badge-active { background: rgba(52, 211, 153, 0.18); color: var(--ok); }
    .badge-rejected { background: rgba(248, 113, 113, 0.18); color: var(--bad); }
    .badge-reverted { background: rgba(251, 191, 36, 0.18); color: var(--warn); }
    .badge-proposed { background: rgba(56, 189, 248, 0.18); color: var(--accent); }
    #toast {
      margin-bottom: 16px;
      padding: 10px 14px;
      border-radius: 8px;
      background: #1e293b;
      border: 1px solid var(--accent);
      display: none;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>EvolveGate</h1>
        <div class="subtitle">Bounded Closed-Loop Self-Evolution · Zero Slash Commands</div>
      </div>
      <div class="actions">
        <button id="btn-refresh" class="secondary">Refresh</button>
        <button id="btn-check">Dry-Run Check</button>
        <button id="btn-apply">Run &amp; Apply</button>
        <button id="btn-rollback" class="danger">Rollback Active</button>
      </div>
    </header>
    <div id="toast"></div>
    <div id="metrics" class="grid"></div>
    <div class="card">
      <h3>Tunable Parameter Spaces</h3>
      <div id="params">Loading...</div>
    </div>
    <div class="card">
      <h3>Evolution Snapshots</h3>
      <div id="snapshots">Loading...</div>
    </div>
    <div class="card">
      <h3>Golden Examples (Zero-Sum Pool)</h3>
      <div id="golden">Loading...</div>
    </div>
  </div>
<script>
const toast = document.getElementById('toast');
function showToast(msg) {
  toast.textContent = msg;
  toast.style.display = 'block';
  setTimeout(() => { toast.style.display = 'none'; }, 5000);
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
async function loadStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  const t = data.telemetry || {};
  document.getElementById('metrics').innerHTML = `
    <div class="card"><div class="metric-label">Turns (7d)</div><div class="metric-value">${t.turns ?? 0}</div></div>
    <div class="card"><div class="metric-label">Error Rate</div><div class="metric-value">${Number(t.error_pct ?? 0).toFixed(1)}%</div></div>
    <div class="card"><div class="metric-label">Avg Latency</div><div class="metric-value">${Math.round(t.mean_latency_ms ?? 0)} ms</div></div>
    <div class="card"><div class="metric-label">Active Snapshot</div><div class="metric-value">${data.active_snapshot ? '#' + data.active_snapshot.id : 'None'}</div></div>
  `;
  const params = data.params || {};
  const spaces = data.spaces || [];
  let pHtml = '<table><tr><th>Space</th><th>Parameter</th><th>Current</th><th>Bounds</th></tr>';
  for (const sp of spaces) {
    for (const spec of sp.specs || []) {
      pHtml += `<tr><td><code>${esc(sp.space_id)}</code></td><td><code>${esc(spec.name)}</code><br><small>${esc(spec.description)}</small></td><td><b>${esc(params[spec.name])}</b></td><td>[${esc(spec.min_val)}, ${esc(spec.max_val)}] step ${esc(spec.step)}</td></tr>`;
    }
  }
  if (!spaces.length) pHtml += '<tr><td colspan="4">No tunable parameter spaces registered yet.</td></tr>';
  pHtml += '</table>';
  document.getElementById('params').innerHTML = pHtml;

  const snaps = data.snapshots || [];
  let sHtml = '<table><tr><th>ID</th><th>Status</th><th>Created</th><th>Summary</th></tr>';
  for (const sn of snaps) {
    const dt = new Date((sn.created_at || 0) * 1000).toLocaleString();
    sHtml += `<tr><td>#${sn.id}</td><td><span class="badge badge-${esc(sn.status)}">${esc(sn.status)}</span></td><td>${esc(dt)}</td><td>${esc(sn.summary || '')}</td></tr>`;
  }
  if (!snaps.length) sHtml += '<tr><td colspan="4">No snapshots yet.</td></tr>';
  sHtml += '</table>';
  document.getElementById('snapshots').innerHTML = sHtml;

  const golden = data.golden_examples || [];
  let gHtml = '<table><tr><th>ID</th><th>Utility</th><th>Hits</th><th>Example</th></tr>';
  for (const g of golden) {
    gHtml += `<tr><td>#${g.id}</td><td>${Number(g.utility_score || 0).toFixed(2)}</td><td>${g.hit_count || 0}</td><td>${esc(g.text)}</td></tr>`;
  }
  if (!golden.length) gHtml += '<tr><td colspan="4">No golden examples stored yet.</td></tr>';
  gHtml += '</table>';
  document.getElementById('golden').innerHTML = gHtml;
}
async function postAction(path) {
  const res = await fetch(path, { method: 'POST' });
  const data = await res.json();
  showToast(path + ': ' + JSON.stringify(data));
  await loadStatus();
}
document.getElementById('btn-refresh').onclick = loadStatus;
document.getElementById('btn-check').onclick = () => postAction('/api/check');
document.getElementById('btn-apply').onclick = () => postAction('/api/apply');
document.getElementById('btn-rollback').onclick = () => postAction('/api/rollback');
loadStatus();
</script>
</body>
</html>
"""


def build_status_payload(store: EvolveStore, api: EvolveGateAPI, *, now_ts: int | None = None) -> dict[str, Any]:
    """Assemble JSON status payload for both Dashboard and CLI."""
    now = int(time.time() if now_ts is None else now_ts)
    since_ts = now - 7 * 86400
    _, current_params = api.collect_current_params()
    return {
        "ok": True,
        "timestamp": now,
        "telemetry": store.summarize_telemetry(since_ts=since_ts),
        "params": current_params,
        "spaces": api.list_spaces(),
        "api": api.describe(),
        "active_snapshot": store.latest_active_snapshot(),
        "snapshots": store.list_snapshots(limit=15),
        "golden_examples": store.list_golden_examples(limit=20),
        "last_evolution_ts": int(store.get_kv("last_evolution_ts", "0") or 0),
    }


async def rollback_active_snapshot(
    store: EvolveStore,
    api: EvolveGateAPI,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Restore previous parameters from the latest active snapshot."""
    now = int(time.time() if now_ts is None else now_ts)
    active = store.latest_active_snapshot()
    if not active:
        return {"ok": False, "action": "rollback", "reason": "no_active_snapshot"}
    prev_params = active.get("prev_params") or {}
    applied = await api.apply_params(prev_params) if prev_params else True
    store.update_snapshot_status(int(active["id"]), "reverted", now_ts=now)
    return {
        "ok": bool(applied),
        "action": "rollback",
        "snapshot_id": int(active["id"]),
        "restored": prev_params,
    }


def create_dashboard_app(
    store: EvolveStore,
    api: EvolveGateAPI,
    *,
    max_golden_examples: int = 10,
    auto_rollback_hours: int = 48,
) -> web.Application:
    """Create the aiohttp Application for EvolveGate's local Web Dashboard."""
    app = web.Application()

    async def handle_index(_request: web.Request) -> web.Response:
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")

    async def handle_status(_request: web.Request) -> web.Response:
        payload = build_status_payload(store, api)
        return web.json_response(payload)

    async def handle_check(_request: web.Request) -> web.Response:
        result = await run_evolution_cycle(
            store,
            api,
            max_golden_examples=max_golden_examples,
            auto_apply=False,
            auto_rollback_hours=auto_rollback_hours,
        )
        return web.json_response({"ok": True, "result": result})

    async def handle_apply(_request: web.Request) -> web.Response:
        result = await run_evolution_cycle(
            store,
            api,
            max_golden_examples=max_golden_examples,
            auto_apply=True,
            auto_rollback_hours=auto_rollback_hours,
        )
        return web.json_response({"ok": True, "result": result})

    async def handle_rollback(_request: web.Request) -> web.Response:
        result = await rollback_active_snapshot(store, api)
        return web.json_response(result)

    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/check", handle_check)
    app.router.add_post("/api/apply", handle_apply)
    app.router.add_post("/api/rollback", handle_rollback)
    return app


class DashboardServer:
    """Lifecycle wrapper for EvolveGate's embedded aiohttp server."""

    def __init__(
        self,
        store: EvolveStore,
        api: EvolveGateAPI,
        *,
        host: str = "127.0.0.1",
        port: int = 8557,
        max_golden_examples: int = 10,
        auto_rollback_hours: int = 48,
    ) -> None:
        self.store = store
        self.api = api
        self.host = host
        self.port = int(port)
        self.max_golden_examples = max_golden_examples
        self.auto_rollback_hours = auto_rollback_hours
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        if self._runner is not None:
            return
        app = create_dashboard_app(
            self.store,
            self.api,
            max_golden_examples=self.max_golden_examples,
            auto_rollback_hours=self.auto_rollback_hours,
        )
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self._runner = runner
        self._site = site

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None


__all__ = [
    "DashboardServer",
    "build_status_payload",
    "create_dashboard_app",
    "rollback_active_snapshot",
]
