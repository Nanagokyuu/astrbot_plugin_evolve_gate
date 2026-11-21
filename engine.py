"""Pure Python bounded closed-loop evolution engine for EvolveGate."""

from __future__ import annotations

import time
from typing import Any

try:
    from .api import EvolveGateAPI, TunableParamSpec
    from .store import EvolveStore
except ImportError:
    from api import EvolveGateAPI, TunableParamSpec
    from store import EvolveStore


def clamp_param_value(val: float | int, spec: TunableParamSpec) -> float | int:
    lo = min(spec.min_val, spec.max_val)
    hi = max(spec.min_val, spec.max_val)
    clamped = max(lo, min(hi, float(val)))
    if spec.kind == "int":
        return int(round(clamped))
    return round(clamped, 3)


def propose_bounded_param_diff(
    specs: dict[str, TunableParamSpec],
    current: dict[str, float | int],
    telemetry: dict[str, Any],
) -> tuple[dict[str, float | int], str]:
    """Generate a safe, strictly bounded L0 parameter proposal from telemetry signals."""
    proposed = dict(current)
    notes: list[str] = []
    mean_chars = float(telemetry.get("mean_chars") or 0.0)
    short_pct = float(telemetry.get("short_le10_pct") or 0.0)
    turns = int(telemetry.get("turns") or 0)

    if turns >= 8:
        if "bubble_soft_max_chars" in specs and "bubble_soft_max_chars" in proposed:
            sp = specs["bubble_soft_max_chars"]
            cur = float(proposed["bubble_soft_max_chars"])
            if short_pct < 35.0 and mean_chars > 14.0 and cur > sp.min_val:
                proposed["bubble_soft_max_chars"] = clamp_param_value(cur - sp.step, sp)
                notes.append("收紧气泡软上限以提升短句节奏")
        if "meme_cooldown_turns" in specs and "meme_cooldown_turns" in proposed:
            sp = specs["meme_cooldown_turns"]
            cur = float(proposed["meme_cooldown_turns"])
            if short_pct < 30.0 and cur > sp.min_val:
                proposed["meme_cooldown_turns"] = clamp_param_value(cur - sp.step, sp)
                notes.append("适度放宽表情包轮次冷却")

    summary = "；".join(notes) if notes else "当前指标平稳，维持参数或仅做黄金台词新陈代谢"
    return proposed, summary


def check_auto_rollback_needed(
    store: EvolveStore,
    *,
    auto_rollback_hours: int = 48,
    now_ts: int | None = None,
) -> dict[str, Any] | None:
    """Return active snapshot to revert if post-apply error rate spikes inside observation window."""
    snap = store.latest_active_snapshot()
    if not snap or int(snap.get("applied_at") or 0) <= 0:
        return None
    ts = int(now_ts or time.time())
    applied_at = int(snap["applied_at"])
    window_sec = max(1, int(auto_rollback_hours)) * 3600
    if (ts - applied_at) > window_sec:
        return None
    post_tel = store.summarize_telemetry(since_ts=applied_at)
    if int(post_tel.get("turns") or 0) >= 8 and float(post_tel.get("error_pct") or 0.0) >= 25.0:
        return snap
    return None


async def run_evolution_cycle(
    store: EvolveStore,
    api: EvolveGateAPI,
    *,
    max_golden_examples: int = 10,
    auto_apply: bool = True,
    auto_rollback_hours: int = 48,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Execute one offline evolution cycle: rollback check -> golden metabolism -> bounded proposal -> gate."""
    ts = int(now_ts or time.time())
    rollback_target = check_auto_rollback_needed(store, auto_rollback_hours=auto_rollback_hours, now_ts=ts)
    if rollback_target is not None:
        prev_params = rollback_target.get("prev_params") or {}
        if prev_params:
            await api.apply_params(prev_params)
        store.update_snapshot_status(int(rollback_target["id"]), "reverted", now_ts=ts)
        return {"action": "auto_reverted", "snapshot_id": int(rollback_target["id"])}

    telemetry = store.summarize_telemetry(since_ts=ts - 86400)
    golden_added = 0
    for sample in (telemetry.get("samples") or [])[:2]:
        if store.upsert_golden_example_zero_sum(
            text=sample,
            max_slots=max_golden_examples,
            utility_score=0.85,
            now_ts=ts,
        ):
            golden_added += 1

    specs, current = api.collect_current_params()
    if not specs:
        return {
            "action": "golden_only",
            "telemetry": telemetry,
            "golden_added": golden_added,
        }

    proposed, summary = propose_bounded_param_diff(specs, current, telemetry)
    passed, score, gate_report = await api.run_gates(proposed, telemetry)
    changed = any(proposed.get(k) != current.get(k) for k in proposed)

    status = "active" if (passed and auto_apply and changed) else ("rejected" if not passed else "proposed")
    snap_id = store.create_snapshot(
        params=proposed,
        prev_params=current,
        gate_passed=passed,
        gate_score=score,
        gate_report=gate_report,
        summary=summary,
        status=status,
        now_ts=ts,
    )
    if status == "active":
        await api.apply_params(proposed)

    return {
        "action": status,
        "snapshot_id": snap_id,
        "gate_passed": passed,
        "gate_score": score,
        "golden_added": golden_added,
        "summary": summary,
        "telemetry": telemetry,
    }
