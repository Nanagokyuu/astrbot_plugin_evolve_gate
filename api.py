"""Public extension API (evolve-gate.v1), reload-safe on sys."""

from __future__ import annotations

import inspect
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PLUGIN_ID = "astrbot_plugin_evolve_gate"
API_VERSION = "evolve-gate.v1"
REGISTRY_KINDS = ("tunable_space", "regression_gate", "telemetry_enricher")
_REGISTRY_KEY = "_astrbot_evolve_gate_registry_v1"


@dataclass(frozen=True)
class TunableParamSpec:
    name: str
    kind: str  # "int" | "float"
    min_val: float
    max_val: float
    step: float = 1.0
    description: str = ""


@dataclass
class _Reg:
    token: str
    kind: str
    name: str
    priority: int
    payload: Any


def _shared_registry() -> dict[str, list[_Reg]]:
    reg = getattr(sys, _REGISTRY_KEY, None)
    if not isinstance(reg, dict):
        reg = {}
        setattr(sys, _REGISTRY_KEY, reg)
    for k in REGISTRY_KINDS:
        if not isinstance(reg.get(k), list):
            reg[k] = []
    return reg


_REGISTRY: dict[str, list[_Reg]] = _shared_registry()


class EvolveGateAPI:
    """Extension API allowing downstream plugins to register bounded params & regression gates."""

    api_version = API_VERSION
    plugin_id = PLUGIN_ID

    def __init__(self) -> None:
        self._spaces = _REGISTRY["tunable_space"]
        self._gates = _REGISTRY["regression_gate"]
        self._enrichers = _REGISTRY["telemetry_enricher"]

    def _add(self, bucket: list[_Reg], kind: str, name: str, priority: int, payload: Any) -> str:
        clean = str(name or kind).strip() or kind
        bucket[:] = [item for item in bucket if not (item.kind == kind and item.name == clean)]
        token = f"{kind}:{clean}:{uuid.uuid4().hex[:10]}"
        bucket.append(_Reg(token=token, kind=kind, name=clean, priority=int(priority), payload=payload))
        bucket.sort(key=lambda item: (item.priority, item.name))
        return token

    def register_tunable_space(
        self,
        space_id: str,
        *,
        specs: list[TunableParamSpec],
        getter: Callable[[], dict[str, float | int]],
        applier: Callable[[dict[str, float | int]], Any],
        priority: int = 100,
    ) -> str:
        return self._add(
            self._spaces,
            "tunable_space",
            space_id,
            priority,
            {"specs": list(specs), "getter": getter, "applier": applier},
        )

    def register_regression_gate(
        self,
        gate_id: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        priority: int = 100,
    ) -> str:
        if not callable(fn):
            raise TypeError("regression_gate callback must be callable")
        return self._add(self._gates, "regression_gate", gate_id, priority, fn)

    def register_telemetry_enricher(
        self,
        enricher_id: str,
        fn: Callable[[], dict[str, Any]],
        *,
        priority: int = 100,
    ) -> str:
        if not callable(fn):
            raise TypeError("telemetry_enricher callback must be callable")
        return self._add(self._enrichers, "telemetry_enricher", enricher_id, priority, fn)

    def unregister(self, token: str) -> bool:
        for bucket in (self._spaces, self._gates, self._enrichers):
            for idx, item in enumerate(bucket):
                if item.token == token:
                    bucket.pop(idx)
                    return True
        return False

    @classmethod
    def reset_registry(cls) -> None:
        for bucket in _REGISTRY.values():
            bucket.clear()

    def describe(self) -> dict[str, int]:
        return {
            "tunable_spaces": len(self._spaces),
            "regression_gates": len(self._gates),
            "telemetry_enrichers": len(self._enrichers),
        }

    def collect_current_params(self) -> tuple[dict[str, TunableParamSpec], dict[str, float | int]]:
        specs: dict[str, TunableParamSpec] = {}
        current: dict[str, float | int] = {}
        for reg in list(self._spaces):
            p = reg.payload
            for sp in p["specs"]:
                specs[sp.name] = sp
            try:
                vals = p["getter"]()
                if isinstance(vals, dict):
                    current.update(vals)
            except Exception:
                continue
        return specs, current

    async def apply_params(self, params: dict[str, float | int]) -> bool:
        ok = True
        for reg in list(self._spaces):
            applier = reg.payload["applier"]
            try:
                res = applier(dict(params))
                if inspect.isawaitable(res):
                    await res
            except Exception:
                ok = False
        return ok

    async def run_gates(self, candidate_params: dict[str, Any], telemetry: dict[str, Any]) -> tuple[bool, float, dict[str, Any]]:
        if not self._gates:
            return True, 1.0, {"default_gate": {"passed": True, "score": 1.0, "reason": "no_custom_gates"}}
        results: dict[str, Any] = {}
        all_passed = True
        scores: list[float] = []
        for reg in list(self._gates):
            try:
                res = reg.payload({"params": dict(candidate_params), "telemetry": dict(telemetry)})
                if inspect.isawaitable(res):
                    res = await res
                passed = bool((res or {}).get("passed", False))
                score = float((res or {}).get("score", 1.0 if passed else 0.0))
                results[reg.name] = {"passed": passed, "score": score, "reason": str((res or {}).get("reason", ""))}
                if not passed:
                    all_passed = False
                scores.append(score)
            except Exception as exc:
                all_passed = False
                scores.append(0.0)
                results[reg.name] = {"passed": False, "score": 0.0, "reason": f"error:{exc}"}
        avg_score = round(sum(scores) / len(scores), 4) if scores else 1.0
        return all_passed, avg_score, results

    def list_spaces(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for reg in list(self._spaces):
            specs = [
                {
                    "name": sp.name,
                    "kind": sp.kind,
                    "min_val": sp.min_val,
                    "max_val": sp.max_val,
                    "step": sp.step,
                    "description": sp.description,
                }
                for sp in reg.payload["specs"]
            ]
            out.append({"space_id": reg.name, "specs": specs})
        return out

    def iter_telemetry_enrichers(self) -> list[tuple[str, Callable[..., dict[str, Any]]]]:
        return [(reg.name, reg.payload) for reg in list(self._enrichers)]


def get_evolve_gate_api() -> EvolveGateAPI:
    """Return an EvolveGateAPI instance backed by the reload-safe process registry."""
    return EvolveGateAPI()
