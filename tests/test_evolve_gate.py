"""Unit tests for astrbot_plugin_evolve_gate."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from api import EvolveGateAPI, TunableParamSpec  # noqa: E402
from dashboard import create_dashboard_app  # noqa: E402
from engine import clamp_param_value, propose_bounded_param_diff, run_evolution_cycle  # noqa: E402
from store import EvolveStore  # noqa: E402


def test_store_zero_sum_golden_examples(tmp_path: Path) -> None:
    store = EvolveStore(tmp_path / "eg.db")
    for idx in range(5):
        store.upsert_golden_example_zero_sum(
            text=f"example reply {idx}",
            max_slots=3,
            utility_score=float(idx + 1),
            now_ts=1000 + idx,
        )
    items = store.list_golden_examples(limit=10)
    assert len(items) == 3
    scores = [float(it["utility_score"]) for it in items]
    assert scores == [5.0, 4.0, 3.0]


def test_clamp_and_bounded_diff() -> None:
    spec_soft = TunableParamSpec("bubble_soft_max_chars", "int", 24, 38, step=2)
    assert clamp_param_value(50, spec_soft) == 38
    assert clamp_param_value(10, spec_soft) == 24

    spec_cd = TunableParamSpec("meme_cooldown_turns", "int", 2, 5, step=1)
    specs = {"bubble_soft_max_chars": spec_soft, "meme_cooldown_turns": spec_cd}
    current = {"bubble_soft_max_chars": 30, "meme_cooldown_turns": 3}

    proposed, _summary = propose_bounded_param_diff(
        specs,
        current,
        {"turns": 20, "mean_chars": 18.0, "short_le10_pct": 20.0},
    )
    assert proposed["bubble_soft_max_chars"] == 28
    assert proposed["meme_cooldown_turns"] == 2


def test_evolution_cycle_gate_reject_and_apply_and_rollback(tmp_path: Path) -> None:
    async def _run() -> None:
        EvolveGateAPI.reset_registry()
        store = EvolveStore(tmp_path / "eg.db")
        api = EvolveGateAPI()
        state = {"bubble_soft_max_chars": 30}
        api.register_tunable_space(
            "s1",
            specs=[TunableParamSpec("bubble_soft_max_chars", "int", 24, 38, step=2)],
            getter=lambda: dict(state),
            applier=lambda p: state.update(p),
        )

        for i in range(12):
            store.record_turn(
                scope_key="u1",
                reply_text="这是一句稍微长一点的测试回复内容超过十四个字",
                latency_ms=1000,
                had_error=False,
                now_ts=10_000 + i,
            )

        # Rejecting gate
        tok = api.register_regression_gate("deny", lambda _payload: {"passed": False, "score": 0.0, "reason": "blocked"})
        rejected = await run_evolution_cycle(store, api, auto_apply=True, now_ts=10_100)
        assert rejected["action"] == "rejected"
        assert state["bubble_soft_max_chars"] == 30
        api.unregister(tok)

        # Passing gate -> applies
        api.register_regression_gate("allow", lambda _payload: {"passed": True, "score": 1.0, "reason": "ok"})
        applied = await run_evolution_cycle(store, api, auto_apply=True, now_ts=10_200)
        assert applied["action"] == "active"
        assert state["bubble_soft_max_chars"] == 28

        # Post-apply degradation triggers auto-rollback
        for i in range(10):
            store.record_turn(
                scope_key="u1",
                reply_text="err",
                latency_ms=1000,
                had_error=(i < 4),  # 40% error >= 25%
                now_ts=10_300 + i,
            )
        rolled = await run_evolution_cycle(store, api, auto_apply=True, now_ts=10_400)
        assert rolled["action"] == "auto_reverted"
        assert state["bubble_soft_max_chars"] == 30

    asyncio.run(_run())


def test_dashboard_routes(tmp_path: Path) -> None:
    async def _run() -> None:
        EvolveGateAPI.reset_registry()
        store = EvolveStore(tmp_path / "eg.db")
        api = EvolveGateAPI()
        state = {"bubble_soft_max_chars": 30}
        api.register_tunable_space(
            "s1",
            specs=[TunableParamSpec("bubble_soft_max_chars", "int", 24, 38, step=2)],
            getter=lambda: dict(state),
            applier=lambda p: state.update(p),
        )
        now = int(time.time()) - 100
        for i in range(12):
            store.record_turn(
                scope_key="u1",
                reply_text="这是一句稍微长一点的测试回复内容超过十四个字",
                latency_ms=1200,
                had_error=False,
                now_ts=now + i,
            )

        app = create_dashboard_app(store, api)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 200
            assert "EvolveGate" in await resp.text()

            st_resp = await client.get("/api/status")
            assert st_resp.status == 200
            st_data = await st_resp.json()
            assert st_data["ok"] is True
            assert st_data["params"]["bubble_soft_max_chars"] == 30

            chk_resp = await client.post("/api/check")
            assert chk_resp.status == 200
            chk_data = await chk_resp.json()
            assert chk_data["result"]["action"] == "proposed"
            assert state["bubble_soft_max_chars"] == 30

            app_resp = await client.post("/api/apply")
            assert app_resp.status == 200
            app_data = await app_resp.json()
            assert app_data["result"]["action"] == "active"
            assert state["bubble_soft_max_chars"] == 28

            rb_resp = await client.post("/api/rollback")
            assert rb_resp.status == 200
            rb_data = await rb_resp.json()
            assert rb_data["ok"] is True
            assert state["bubble_soft_max_chars"] == 30

    asyncio.run(_run())
