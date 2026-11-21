"""SQLite persistence for EvolveGate (telemetry, zero-sum golden examples, and snapshots)."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS telemetry_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key TEXT NOT NULL,
    channel_type TEXT NOT NULL DEFAULT 'private',
    reply_chars INTEGER NOT NULL DEFAULT 0,
    ended_with_period INTEGER NOT NULL DEFAULT 0,
    ended_with_question INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    had_error INTEGER NOT NULL DEFAULT 0,
    user_followup_quick INTEGER NOT NULL DEFAULT 0,
    sample_reply TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eg_tel_ts ON telemetry_turns(created_at DESC);

CREATE TABLE IF NOT EXISTS golden_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL UNIQUE,
    reply_chars INTEGER NOT NULL DEFAULT 0,
    utility_score REAL NOT NULL DEFAULT 0.8,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS evolution_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    params_json TEXT NOT NULL,
    prev_params_json TEXT NOT NULL DEFAULT '{}',
    gate_passed INTEGER NOT NULL DEFAULT 0,
    gate_score REAL NOT NULL DEFAULT 0.0,
    gate_report_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT DEFAULT '',
    applied_at INTEGER NOT NULL DEFAULT 0,
    reverted_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv_state (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


class EvolveStore:
    """Thread-safe SQLite store for EvolveGate."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(str(self.db_path), timeout=5.0)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def record_turn(
        self,
        *,
        scope_key: str,
        channel_type: str = "private",
        reply_text: str = "",
        latency_ms: int = 0,
        had_error: bool = False,
        user_followup_quick: bool = False,
        now_ts: int | None = None,
    ) -> int:
        ts = int(now_ts or time.time())
        clean = str(reply_text or "").strip()
        chars = len(clean.replace("\n", ""))
        ended_period = 1 if clean.endswith("。") else 0
        ended_q = 1 if clean.endswith(("?", "？")) else 0
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO telemetry_turns
                (scope_key, channel_type, reply_chars, ended_with_period, ended_with_question, latency_ms, had_error, user_followup_quick, sample_reply, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_key,
                    channel_type,
                    chars,
                    ended_period,
                    ended_q,
                    max(0, int(latency_ms)),
                    1 if had_error else 0,
                    1 if user_followup_quick else 0,
                    clean[:80],
                    ts,
                ),
            )
            return int(cur.lastrowid or 0)

    def summarize_telemetry(self, *, since_ts: int) -> dict[str, Any]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM telemetry_turns WHERE created_at >= ? ORDER BY id DESC LIMIT 500",
                (int(since_ts),),
            ).fetchall()
        if not rows:
            return {
                "turns": 0,
                "mean_chars": 0.0,
                "short_le10_pct": 0.0,
                "period_end_pct": 0.0,
                "question_pct": 0.0,
                "error_pct": 0.0,
                "mean_latency_ms": 0.0,
                "samples": [],
            }
        n = len(rows)
        chars = [int(r["reply_chars"]) for r in rows]
        short_cnt = sum(1 for c in chars if 0 < c <= 10)
        period_cnt = sum(int(r["ended_with_period"]) for r in rows)
        q_cnt = sum(int(r["ended_with_question"]) for r in rows)
        err_cnt = sum(int(r["had_error"]) for r in rows)
        lats = [int(r["latency_ms"]) for r in rows if int(r["latency_ms"]) > 0]
        samples = [
            str(r["sample_reply"]).strip()
            for r in rows
            if str(r["sample_reply"] or "").strip()
            and int(r["had_error"]) == 0
            and int(r["ended_with_period"]) == 0
            and 2 <= int(r["reply_chars"]) <= 24
        ][:12]
        return {
            "turns": n,
            "mean_chars": round(sum(chars) / n, 1),
            "short_le10_pct": round(short_cnt / n * 100.0, 1),
            "period_end_pct": round(period_cnt / n * 100.0, 1),
            "question_pct": round(q_cnt / n * 100.0, 1),
            "error_pct": round(err_cnt / n * 100.0, 1),
            "mean_latency_ms": round(sum(lats) / len(lats), 1) if lats else 0.0,
            "samples": samples,
        }

    def list_golden_examples(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM golden_examples ORDER BY utility_score DESC, hit_count DESC, id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_golden_example_zero_sum(
        self,
        *,
        text: str,
        max_slots: int = 10,
        utility_score: float = 0.85,
        now_ts: int | None = None,
    ) -> bool:
        """Insert a golden example while strictly capping table size to max_slots (evicting lowest-utility/LRU)."""
        clean = str(text or "").strip()[:60]
        if len(clean) < 2:
            return False
        ts = int(now_ts or time.time())
        cap = max(1, int(max_slots))
        with self._connect() as con:
            existing = con.execute("SELECT id FROM golden_examples WHERE text = ?", (clean,)).fetchone()
            if existing:
                con.execute(
                    "UPDATE golden_examples SET utility_score = MAX(utility_score, ?), last_hit_at = ? WHERE id = ?",
                    (float(utility_score), ts, int(existing["id"])),
                )
                return False
            cnt = int(con.execute("SELECT COUNT(*) FROM golden_examples").fetchone()[0])
            while cnt >= cap:
                victim = con.execute(
                    "SELECT id FROM golden_examples ORDER BY utility_score ASC, hit_count ASC, last_hit_at ASC, id ASC LIMIT 1"
                ).fetchone()
                if not victim:
                    break
                con.execute("DELETE FROM golden_examples WHERE id = ?", (int(victim["id"]),))
                cnt -= 1
            con.execute(
                """
                INSERT INTO golden_examples (text, reply_chars, utility_score, hit_count, last_hit_at, created_at)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (clean, len(clean), float(utility_score), ts, ts),
            )
            return True

    def mark_golden_hits(self, ids: list[int], *, now_ts: int | None = None) -> None:
        clean_ids = [int(x) for x in ids if int(x) > 0]
        if not clean_ids:
            return
        ts = int(now_ts or time.time())
        placeholders = ",".join("?" for _ in clean_ids)
        with self._connect() as con:
            con.execute(
                f"UPDATE golden_examples SET hit_count = hit_count + 1, last_hit_at = ? WHERE id IN ({placeholders})",
                [ts, *clean_ids],
            )

    def create_snapshot(
        self,
        *,
        params: dict[str, Any],
        prev_params: dict[str, Any],
        gate_passed: bool,
        gate_score: float,
        gate_report: dict[str, Any],
        summary: str,
        status: str = "proposed",
        now_ts: int | None = None,
    ) -> int:
        ts = int(now_ts or time.time())
        with self._connect() as con:
            row = con.execute("SELECT COALESCE(MAX(generation), 0) FROM evolution_snapshots").fetchone()
            gen = int(row[0] if row else 0) + 1
            cur = con.execute(
                """
                INSERT INTO evolution_snapshots
                (generation, status, params_json, prev_params_json, gate_passed, gate_score, gate_report_json, summary, applied_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gen,
                    status,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(prev_params, ensure_ascii=False),
                    1 if gate_passed else 0,
                    float(gate_score),
                    json.dumps(gate_report, ensure_ascii=False),
                    summary[:300],
                    ts if status == "active" else 0,
                    ts,
                ),
            )
            return int(cur.lastrowid or 0)

    def update_snapshot_status(self, snap_id: int, status: str, *, now_ts: int | None = None) -> None:
        ts = int(now_ts or time.time())
        with self._connect() as con:
            if status == "active":
                con.execute(
                    "UPDATE evolution_snapshots SET status = 'active', applied_at = ? WHERE id = ?",
                    (ts, int(snap_id)),
                )
            elif status == "reverted":
                con.execute(
                    "UPDATE evolution_snapshots SET status = 'reverted', reverted_at = ? WHERE id = ?",
                    (ts, int(snap_id)),
                )
            else:
                con.execute(
                    "UPDATE evolution_snapshots SET status = ? WHERE id = ?",
                    (status, int(snap_id)),
                )

    def latest_active_snapshot(self) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM evolution_snapshots WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return self._decode_snapshot(row)

    def list_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM evolution_snapshots ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [self._decode_snapshot(r) for r in rows if r is not None]

    @staticmethod
    def _decode_snapshot(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        for key, target in (("params_json", "params"), ("prev_params_json", "prev_params"), ("gate_report_json", "gate_report")):
            try:
                d[target] = json.loads(d.get(key) or "{}")
            except Exception:
                d[target] = {}
        return d

    def get_kv(self, key: str, default: str = "") -> str:
        with self._connect() as con:
            row = con.execute("SELECT v FROM kv_state WHERE k = ?", (key,)).fetchone()
            return str(row["v"]) if row else default

    def set_kv(self, key: str, value: str, *, now_ts: int | None = None) -> None:
        ts = int(now_ts or time.time())
        with self._connect() as con:
            con.execute(
                "INSERT INTO kv_state (k, v, updated_at) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at",
                (key, str(value), ts),
            )
