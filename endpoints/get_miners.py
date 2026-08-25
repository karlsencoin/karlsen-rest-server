# encoding: utf-8
"""
KGI miners endpoints — reads snapshots written by karlsen_reward_tracker.py
from the shared SQLite database at $KGI_TRACKER_DB (default
/opt/karlsen/kgi/kgi.db) and exposes them under /info/miners/*.

Registered by import side-effect in main.py, matching the pattern used by
the other endpoints/ modules in this project.
"""

import os
import sqlite3
import time
from typing import Optional

from fastapi import HTTPException, Query

from server import app

DB_PATH = os.getenv("KGI_TRACKER_DB", "/opt/karlsen/kgi/kgi.db")
STALE_AFTER_MS = 90_000


def _connect() -> sqlite3.Connection:
    """Open the shared SQLite DB in read-only mode (WAL-safe)."""
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True,
                               check_same_thread=False)
    except sqlite3.Error as e:
        raise HTTPException(status_code=503,
                            detail=f"tracker db not available: {e}")
    conn.row_factory = sqlite3.Row
    return conn


def _latest_ts(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT ts_ms FROM network_snapshot "
        "ORDER BY ts_ms DESC LIMIT 1").fetchone()
    return row["ts_ms"] if row else None


def _is_stale(ts_ms: Optional[int]) -> bool:
    if ts_ms is None:
        return True
    return (int(time.time() * 1000) - ts_ms) > STALE_AFTER_MS


@app.get("/info/miners/top",
         tags=["Karlsen network info"],
         summary="Latest window snapshot: miner leaderboard + network stats")
async def miners_top(
    limit: int = Query(300, ge=1, le=1000,
                       description="Max miners to return (default 300)."),
):
    conn = _connect()
    try:
        ts_ms = _latest_ts(conn)
        if ts_ms is None:
            return {"ts_ms": None, "stale": True, "network": None, "miners": []}

        net = conn.execute(
            "SELECT network_hps, window_blocks, active_miners, "
            "       window_minutes, min_blocks_gate "
            "FROM network_snapshot WHERE ts_ms = ?", (ts_ms,)
        ).fetchone()

        miners = conn.execute(
            "SELECT address, blocks_in_window, window_sompi, "
            "       hashrate_hs, winrate, alltime_sompi "
            "FROM miner_snapshot WHERE ts_ms = ? "
            "ORDER BY hashrate_hs DESC LIMIT ?",
            (ts_ms, limit)).fetchall()

        return {
            "ts_ms": ts_ms,
            "stale": _is_stale(ts_ms),
            "network": {
                "hashrate_hs": net["network_hps"],
                "window_blocks": net["window_blocks"],
                "active_miners": net["active_miners"],
                "window_minutes": net["window_minutes"],
                "min_blocks_gate": net["min_blocks_gate"],
            } if net else None,
            "miners": [
                {
                    "address": m["address"],
                    "blocks": m["blocks_in_window"],
                    "window_kls": m["window_sompi"] / 1e8,
                    "hashrate_hs": m["hashrate_hs"],
                    "winrate": m["winrate"],
                    "alltime_kls": m["alltime_sompi"] / 1e8,
                }
                for m in miners
            ],
        }
    finally:
        conn.close()


@app.get("/info/miners/network",
         tags=["Karlsen network info"],
         summary="Network-level snapshot only (cheap poll)")
async def miners_network():
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT ts_ms, network_hps, window_blocks, active_miners, "
            "       window_minutes, min_blocks_gate "
            "FROM network_snapshot ORDER BY ts_ms DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {"ts_ms": None, "stale": True}
        return {
            "ts_ms": row["ts_ms"],
            "stale": _is_stale(row["ts_ms"]),
            "hashrate_hs": row["network_hps"],
            "window_blocks": row["window_blocks"],
            "active_miners": row["active_miners"],
            "window_minutes": row["window_minutes"],
            "min_blocks_gate": row["min_blocks_gate"],
        }
    finally:
        conn.close()


@app.get("/info/miners/address/{address}",
         tags=["Karlsen network info"],
         summary="Per-miner detail: all-time totals + recent snapshot history")
async def miner_detail(
    address: str,
    hours: int = Query(24, ge=1, le=168,
                       description="Snapshot history window in hours (1-168)."),
):
    if not address.startswith("karlsen:"):
        raise HTTPException(status_code=400,
                            detail="address must start with 'karlsen:'")
    conn = _connect()
    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n_blocks, "
            "       COALESCE(SUM(amount_sompi), 0) AS total_sompi, "
            "       MIN(timestamp_ms) AS first_seen_ms, "
            "       MAX(timestamp_ms) AS last_seen_ms "
            "FROM miner_blocks WHERE address = ?", (address,)
        ).fetchone()

        cutoff = int(time.time() * 1000) - hours * 3600 * 1000
        history = conn.execute(
            "SELECT ts_ms, blocks_in_window, hashrate_hs, winrate "
            "FROM miner_snapshot WHERE address = ? AND ts_ms >= ? "
            "ORDER BY ts_ms ASC", (address, cutoff)
        ).fetchall()

        return {
            "address": address,
            "alltime": {
                "blocks": total_row["n_blocks"],
                "total_kls": total_row["total_sompi"] / 1e8,
                "first_seen_ms": total_row["first_seen_ms"],
                "last_seen_ms": total_row["last_seen_ms"],
            },
            "history": [
                {
                    "ts_ms": h["ts_ms"],
                    "blocks": h["blocks_in_window"],
                    "hashrate_hs": h["hashrate_hs"],
                    "winrate": h["winrate"],
                }
                for h in history
            ],
        }
    finally:
        conn.close()
