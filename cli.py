"""CLI tool for inspecting and controlling EvolveGate outside chat."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

try:
    from .api import get_evolve_gate_api
    from .dashboard import build_status_payload, rollback_active_snapshot
    from .engine import run_evolution_cycle
    from .store import EvolveStore
except ImportError:
    from api import get_evolve_gate_api
    from dashboard import build_status_payload, rollback_active_snapshot
    from engine import run_evolution_cycle
    from store import EvolveStore


DEFAULT_DB_PATH = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_evolve_gate"
    / "evolve_gate.db"
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evolve-gate",
        description="Inspect and manage AstrBot EvolveGate without slash commands.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to evolve_gate.db SQLite database",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show telemetry, tunable spaces, and snapshots")
    sub.add_parser("check", help="Run a dry-run evolution cycle without applying")
    sub.add_parser("apply", help="Run an evolution cycle and apply if gates pass")
    sub.add_parser("rollback", help="Roll back the latest active snapshot")

    args = parser.parse_args(list(argv) if argv is not None else None)
    store = EvolveStore(args.db)
    api = get_evolve_gate_api()

    if args.command == "status":
        out = build_status_payload(store, api)
    elif args.command == "check":
        out = asyncio.run(run_evolution_cycle(store, api, auto_apply=False))
    elif args.command == "apply":
        out = asyncio.run(run_evolution_cycle(store, api, auto_apply=True))
    elif args.command == "rollback":
        out = asyncio.run(rollback_active_snapshot(store, api))
    else:  # pragma: no cover
        parser.error(f"Unknown command: {args.command}")
        return 2

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
