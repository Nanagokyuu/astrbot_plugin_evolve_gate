"""Built-in Web Dashboard for EvolveGate (default 0.0.0.0:8557)."""

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
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light dark" />
  <title>EvolveGate · 自进化治理看板</title>
  <style>
    :root {
      --bg: #f8fafc;
      --card: #ffffff;
      --border: #e2e8f0;
      --text: #0f172a;
      --muted: #64748b;
      --accent: #0284c7;
      --accent-fg: #ffffff;
      --secondary-bg: #e2e8f0;
      --secondary-fg: #0f172a;
      --code-bg: #f1f5f9;
      --ok: #059669;
      --ok-bg: rgba(16, 185, 129, 0.14);
      --warn: #d97706;
      --warn-bg: rgba(245, 158, 11, 0.15);
      --bad: #dc2626;
      --bad-bg: rgba(239, 68, 68, 0.14);
      --info: #0284c7;
      --info-bg: rgba(14, 165, 233, 0.14);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f172a;
        --card: #1e293b;
        --border: #334155;
        --text: #f1f5f9;
        --muted: #94a3b8;
        --accent: #38bdf8;
        --accent-fg: #0f172a;
        --secondary-bg: #334155;
        --secondary-fg: #f1f5f9;
        --code-bg: #0f172a;
        --ok: #34d399;
        --ok-bg: rgba(52, 211, 153, 0.18);
        --warn: #fbbf24;
        --warn-bg: rgba(251, 191, 36, 0.18);
        --bad: #f87171;
        --bad-bg: rgba(248, 113, 113, 0.18);
        --info: #38bdf8;
        --info-bg: rgba(56, 189, 248, 0.18);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      transition: background-color 0.2s ease, color 0.2s ease;
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
    h3 { margin-top: 0; font-size: 1.05rem; }
    .subtitle { color: var(--muted); font-size: 0.9rem; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    button {
      background: var(--accent);
      color: var(--accent-fg);
      border: none;
      padding: 8px 12px;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      text-align: center;
    }
    .actions button { width: 132px; flex: 0 0 132px; }
    .actions button#btn-lang { width: 64px; flex: 0 0 64px; }
    button.secondary { background: var(--secondary-bg); color: var(--secondary-fg); }
    button.danger { background: var(--bad); color: #ffffff; }
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
      background: var(--code-bg);
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
    .badge-active { background: var(--ok-bg); color: var(--ok); }
    .badge-rejected { background: var(--bad-bg); color: var(--bad); }
    .badge-reverted { background: var(--warn-bg); color: var(--warn); }
    .badge-proposed { background: var(--info-bg); color: var(--info); }
    #toast {
      margin-bottom: 16px;
      padding: 10px 14px;
      border-radius: 8px;
      background: var(--card);
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
        <div id="subtitle" class="subtitle">有界闭环自进化治理看板 · 零聊天斜杠命令</div>
      </div>
      <div class="actions">
        <button id="btn-lang" class="secondary">EN</button>
        <button id="btn-refresh" class="secondary">刷新状态</button>
        <button id="btn-check">干跑演进检查</button>
        <button id="btn-apply">执行并应用</button>
        <button id="btn-rollback" class="danger">回滚当前快照</button>
      </div>
    </header>
    <div id="toast"></div>
    <div id="metrics" class="grid"></div>
    <div class="card">
      <h3 id="title-params">L0 有界可调参数空间</h3>
      <div id="params">加载中...</div>
    </div>
    <div class="card">
      <h3 id="title-snapshots">演进快照历史</h3>
      <div id="snapshots">加载中...</div>
    </div>
    <div class="card">
      <h3 id="title-golden">黄金样本池（零和定额）</h3>
      <div id="golden">加载中...</div>
    </div>
  </div>
<script>
const I18N = {
  zh: {
    subtitle: '有界闭环自进化治理看板 · 零聊天斜杠命令',
    langBtn: 'EN',
    refresh: '刷新状态',
    check: '干跑演进检查',
    apply: '执行并应用',
    rollback: '回滚当前快照',
    titleParams: 'L0 有界可调参数空间',
    titleSnapshots: '演进快照历史',
    titleGolden: '黄金样本池（零和定额）',
    turns7d: '近 7 天对话轮次',
    errorRate: '异常率',
    avgLatency: '平均耗时',
    activeSnap: '当前生效快照',
    none: '无',
    space: '参数空间',
    param: '参数名',
    current: '当前值',
    bounds: '硬边界与步长',
    noSpaces: '暂未注册可调参数空间。',
    id: '编号',
    status: '状态',
    created: '创建时间',
    summary: '变更说明',
    noSnaps: '暂无演进快照记录。',
    utility: '效用分',
    hits: '命中次数',
    example: '样本内容',
    noGolden: '暂无黄金样本记录。',
    step: '步长',
    statuses: { active: '已生效', rejected: '已拦截', reverted: '已回滚', proposed: '待应用' },
    actionDone: '操作完成',
  },
  en: {
    subtitle: 'Bounded Closed-Loop Self-Evolution · Zero Slash Commands',
    langBtn: '中文',
    refresh: 'Refresh',
    check: 'Dry-Run Check',
    apply: 'Run & Apply',
    rollback: 'Rollback Active',
    titleParams: 'Tunable Parameter Spaces',
    titleSnapshots: 'Evolution Snapshots',
    titleGolden: 'Golden Examples (Zero-Sum Pool)',
    turns7d: 'Turns (7d)',
    errorRate: 'Error Rate',
    avgLatency: 'Avg Latency',
    activeSnap: 'Active Snapshot',
    none: 'None',
    space: 'Space',
    param: 'Parameter',
    current: 'Current',
    bounds: 'Bounds',
    noSpaces: 'No tunable parameter spaces registered yet.',
    id: 'ID',
    status: 'Status',
    created: 'Created',
    summary: 'Summary',
    noSnaps: 'No snapshots yet.',
    utility: 'Utility',
    hits: 'Hits',
    example: 'Example',
    noGolden: 'No golden examples stored yet.',
    step: 'step',
    statuses: { active: 'active', rejected: 'rejected', reverted: 'reverted', proposed: 'proposed' },
    actionDone: 'Done',
    descMap: {
      '私聊气泡软字数上限': 'Soft max character limit per private chat bubble',
      '表情包触发轮次冷却': 'Turn cooldown between meme replies',
      '近期切片检索权重': 'Recency weight for voice-slice retrieval',
    },
    summaryMap: {
      '当前指标平稳，维持参数或仅做黄金台词新陈代谢': 'Metrics stable; keep params or metabolize golden examples only',
      '收紧气泡软上限以提升短句节奏': 'Tighten bubble soft limit to improve short-burst pacing',
      '适度放宽表情包轮次冷却': 'Slightly relax meme cooldown turns',
    },
  }
};
let lang = (localStorage.getItem('eg_lang') || (navigator.language.startsWith('zh') ? 'zh' : 'en'));
if (!I18N[lang]) lang = 'zh';
function localizeText(raw, mapObj) {
  const s = String(raw ?? '');
  if (!s || lang !== 'en') return s;
  if (mapObj && mapObj[s]) return mapObj[s];
  if (s.includes('；')) {
    return s.split('；').map(part => (mapObj && mapObj[part.trim()]) || part.trim()).join('; ');
  }
  return s;
}
const toast = document.getElementById('toast');
function showToast(msg) {
  toast.textContent = msg;
  toast.style.display = 'block';
  setTimeout(() => { toast.style.display = 'none'; }, 5000);
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function applyStaticTexts() {
  const t = I18N[lang];
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  document.getElementById('subtitle').textContent = t.subtitle;
  document.getElementById('btn-lang').textContent = t.langBtn;
  document.getElementById('btn-refresh').textContent = t.refresh;
  document.getElementById('btn-check').textContent = t.check;
  document.getElementById('btn-apply').textContent = t.apply;
  document.getElementById('btn-rollback').textContent = t.rollback;
  document.getElementById('title-params').textContent = t.titleParams;
  document.getElementById('title-snapshots').textContent = t.titleSnapshots;
  document.getElementById('title-golden').textContent = t.titleGolden;
}
async function loadStatus() {
  applyStaticTexts();
  const L = I18N[lang];
  const res = await fetch('/api/status');
  const data = await res.json();
  const tel = data.telemetry || {};
  document.getElementById('metrics').innerHTML = `
    <div class="card"><div class="metric-label">${esc(L.turns7d)}</div><div class="metric-value">${tel.turns ?? 0}</div></div>
    <div class="card"><div class="metric-label">${esc(L.errorRate)}</div><div class="metric-value">${Number(tel.error_pct ?? 0).toFixed(1)}%</div></div>
    <div class="card"><div class="metric-label">${esc(L.avgLatency)}</div><div class="metric-value">${Math.round(tel.mean_latency_ms ?? 0)} ms</div></div>
    <div class="card"><div class="metric-label">${esc(L.activeSnap)}</div><div class="metric-value">${data.active_snapshot ? '#' + data.active_snapshot.id : esc(L.none)}</div></div>
  `;
  const params = data.params || {};
  const spaces = data.spaces || [];
  let pHtml = `<table><tr><th>${esc(L.space)}</th><th>${esc(L.param)}</th><th>${esc(L.current)}</th><th>${esc(L.bounds)}</th></tr>`;
  for (const sp of spaces) {
    for (const spec of sp.specs || []) {
      const desc = localizeText(spec.description, L.descMap);
      pHtml += `<tr><td><code>${esc(sp.space_id)}</code></td><td><code>${esc(spec.name)}</code><br><small>${esc(desc)}</small></td><td><b>${esc(params[spec.name])}</b></td><td>[${esc(spec.min_val)}, ${esc(spec.max_val)}] ${esc(L.step)} ${esc(spec.step)}</td></tr>`;
    }
  }
  if (!spaces.length) pHtml += `<tr><td colspan="4">${esc(L.noSpaces)}</td></tr>`;
  pHtml += '</table>';
  document.getElementById('params').innerHTML = pHtml;

  const snaps = data.snapshots || [];
  let sHtml = `<table><tr><th>${esc(L.id)}</th><th>${esc(L.status)}</th><th>${esc(L.created)}</th><th>${esc(L.summary)}</th></tr>`;
  for (const sn of snaps) {
    const dt = new Date((sn.created_at || 0) * 1000).toLocaleString();
    const stLabel = (L.statuses && L.statuses[sn.status]) || sn.status;
    const sumText = localizeText(sn.summary || '', L.summaryMap);
    sHtml += `<tr><td>#${sn.id}</td><td><span class="badge badge-${esc(sn.status)}">${esc(stLabel)}</span></td><td>${esc(dt)}</td><td>${esc(sumText)}</td></tr>`;
  }
  if (!snaps.length) sHtml += `<tr><td colspan="4">${esc(L.noSnaps)}</td></tr>`;
  sHtml += '</table>';
  document.getElementById('snapshots').innerHTML = sHtml;

  const golden = data.golden_examples || [];
  let gHtml = `<table><tr><th>${esc(L.id)}</th><th>${esc(L.utility)}</th><th>${esc(L.hits)}</th><th>${esc(L.example)}</th></tr>`;
  for (const g of golden) {
    gHtml += `<tr><td>#${g.id}</td><td>${Number(g.utility_score || 0).toFixed(2)}</td><td>${g.hit_count || 0}</td><td>${esc(g.text)}</td></tr>`;
  }
  if (!golden.length) gHtml += `<tr><td colspan="4">${esc(L.noGolden)}</td></tr>`;
  gHtml += '</table>';
  document.getElementById('golden').innerHTML = gHtml;
}
async function postAction(path) {
  const res = await fetch(path, { method: 'POST' });
  const data = await res.json();
  showToast(I18N[lang].actionDone + ' (' + path + '): ' + JSON.stringify(data));
  await loadStatus();
}
document.getElementById('btn-lang').onclick = () => {
  lang = lang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('eg_lang', lang);
  loadStatus();
};
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
        host: str = "0.0.0.0",
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
