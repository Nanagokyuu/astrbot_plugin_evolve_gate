"""AstrBot plugin entry point for EvolveGate (zero chat slash commands)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from .api import API_VERSION, PLUGIN_ID, EvolveGateAPI, get_evolve_gate_api
    from .dashboard import DashboardServer
    from .engine import run_evolution_cycle
    from .store import EvolveStore
except ImportError:
    from api import API_VERSION, PLUGIN_ID, EvolveGateAPI, get_evolve_gate_api
    from dashboard import DashboardServer
    from engine import run_evolution_cycle
    from store import EvolveStore


@register(
    PLUGIN_ID,
    "Nanagokyuu",
    "Bounded, regression-gated self-evolution for AstrBot with built-in Web Dashboard (no slash commands).",
    "0.1.0",
    "https://github.com/Nanagokyuu/astrbot_plugin_evolve_gate",
)
class EvolveGatePlugin(Star):
    """Generic AstrBot plugin for bounded parameter evolution & golden example metabolism."""

    API_VERSION = API_VERSION

    def __init__(self, context: Context, config: dict[str, Any] | None = None) -> None:
        super().__init__(context)
        self.config: dict[str, Any] = dict(config or {})
        self.api: EvolveGateAPI = get_evolve_gate_api()

        data_dir = Path("data") / "plugin_data" / PLUGIN_ID
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_ID
        except Exception:
            pass
        self.db_path = data_dir / "evolve_gate.db"
        self.store = EvolveStore(self.db_path)

        self._dashboard: DashboardServer | None = None
        self._scheduler_task: asyncio.Task[Any] | None = None
        self._last_user_turn_ts: dict[str, float] = {}
        self._req_start_ts: dict[str, float] = {}

    def get_api(self) -> EvolveGateAPI:
        """Expose the evolve-gate.v1 registration API to host plugins."""
        return self.api

    def _cfg_bool(self, key: str, default: bool) -> bool:
        val = self.config.get(key, default)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in {"1", "true", "yes", "on"}

    def _cfg_int(self, key: str, default: int, *, minimum: int = 1) -> int:
        try:
            return max(minimum, int(self.config.get(key, default)))
        except (TypeError, ValueError):
            return default

    async def initialize(self) -> None:
        await self._ensure_runtime_started()

    @filter.on_astrbot_loaded()
    async def on_loaded(self, *args: Any, **kwargs: Any) -> None:
        await self._ensure_runtime_started()

    @filter.on_plugin_loaded()
    async def on_plugin_loaded(self, *args: Any, **kwargs: Any) -> None:
        await self._ensure_runtime_started()

    async def _ensure_runtime_started(self) -> None:
        if self._cfg_bool("dashboard_enabled", True) and self._dashboard is None:
            host = str(self.config.get("dashboard_host") or "127.0.0.1")
            port = self._cfg_int("dashboard_port", 8557, minimum=1024)
            srv = DashboardServer(
                self.store,
                self.api,
                host=host,
                port=port,
                max_golden_examples=self._cfg_int("max_golden_examples", 10, minimum=1),
                auto_rollback_hours=self._cfg_int("auto_rollback_hours", 48, minimum=1),
            )
            try:
                await srv.start()
                self._dashboard = srv
                logger.info(f"[evolve_gate] Web Dashboard listening on http://{host}:{port}")
            except Exception as exc:
                logger.warning(f"[evolve_gate] Failed to start dashboard on {host}:{port}: {exc}")

        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(300)
                if not self._cfg_bool("enabled", True):
                    continue
                interval_s = self._cfg_int("evolution_interval_hours", 24, minimum=1) * 3600
                now = int(time.time())
                last_ts = int(self.store.get_kv("last_evolution_ts", "0") or 0)
                if now - last_ts < interval_s:
                    continue
                result = await run_evolution_cycle(
                    self.store,
                    self.api,
                    max_golden_examples=self._cfg_int("max_golden_examples", 10, minimum=1),
                    auto_apply=self._cfg_bool("auto_apply_passed_proposals", True),
                    auto_rollback_hours=self._cfg_int("auto_rollback_hours", 48, minimum=1),
                    now_ts=now,
                )
                self.store.set_kv("last_evolution_ts", str(now), now_ts=now)
                logger.info(f"[evolve_gate] Periodic evolution cycle: {result.get('action')}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"[evolve_gate] Scheduler tick error: {exc}")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: Any) -> None:
        if not self._cfg_bool("enabled", True):
            return
        scope_key = str(getattr(event, "unified_msg_origin", "") or "global")
        now_m = time.monotonic()
        self._req_start_ts[scope_key] = now_m

        if not self._cfg_bool("inject_golden_examples", True):
            return
        if not getattr(self.api, "golden_injection_enabled", True):
            return

        examples = self.store.list_golden_examples(limit=2)
        if not examples:
            return
        lines = ["[Reference Style Examples]"]
        ids: list[int] = []
        for ex in examples:
            ids.append(int(ex["id"]))
            lines.append(f"- {str(ex['text'])[:80]}")
        block = "\n".join(lines)
        cur_sys = str(getattr(req, "system_prompt", "") or "")
        if block not in cur_sys:
            req.system_prompt = f"{cur_sys}\n\n{block}".strip()
            self.store.mark_golden_hits(ids)

    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent) -> None:
        if not self._cfg_bool("enabled", True):
            return
        scope_key = str(getattr(event, "unified_msg_origin", "") or "global")
        now_m = time.monotonic()
        start_m = self._req_start_ts.pop(scope_key, now_m)
        latency_ms = max(0, int((now_m - start_m) * 1000))

        prev_turn = self._last_user_turn_ts.get(scope_key, 0.0)
        quick_followup = prev_turn > 0 and (now_m - prev_turn) <= 90.0
        self._last_user_turn_ts[scope_key] = now_m

        reply_text = ""
        try:
            res = event.get_result()
            if res is not None:
                reply_text = str(res.get_plain_text() or "")
        except Exception:
            reply_text = ""

        is_group = False
        try:
            is_group = bool(event.get_group_id())
        except Exception:
            is_group = False

        extra: dict[str, Any] = {}
        for _, fn in self.api.iter_telemetry_enrichers():
            try:
                out = fn(event, reply_text)
                if isinstance(out, dict):
                    extra.update(out)
            except Exception as exc:
                logger.warning(f"[evolve_gate] Telemetry enricher error: {exc}")

        self.store.record_turn(
            scope_key=scope_key,
            channel_type="group" if is_group else "private",
            reply_text=str(extra.get("reply_text", reply_text)),
            latency_ms=int(extra.get("latency_ms", latency_ms)),
            had_error=bool(extra.get("had_error", False)),
            user_followup_quick=bool(extra.get("user_followup_quick", quick_followup)),
        )

    async def terminate(self) -> None:
        if self._scheduler_task is not None and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        if self._dashboard is not None:
            await self._dashboard.stop()
            self._dashboard = None
        logger.info("[evolve_gate] Terminated cleanly.")
