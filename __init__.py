"""AstrBot Plugin EvolveGate — bounded, zero-slash-command self-evolution."""

from .api import API_VERSION, PLUGIN_ID, EvolveGateAPI, TunableParamSpec, get_evolve_gate_api
from .engine import check_auto_rollback_needed, clamp_param_value, propose_bounded_param_diff, run_evolution_cycle
from .store import EvolveStore

__all__ = [
    "API_VERSION",
    "EvolveGateAPI",
    "EvolveStore",
    "PLUGIN_ID",
    "TunableParamSpec",
    "check_auto_rollback_needed",
    "clamp_param_value",
    "get_evolve_gate_api",
    "propose_bounded_param_diff",
    "run_evolution_cycle",
]
