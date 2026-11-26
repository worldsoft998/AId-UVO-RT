"""SQLite-backed history store.

The store is what makes a campaign *resumable* and *comparable*: every run's
coverage snapshot, every episode record and the merged campaign coverage live in
one portable ``.sqlite`` file next to the logs.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from aiduvo.coverage.model import Bin, CoverageSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY,
    mode        TEXT,
    algorithm   TEXT,
    ai_enabled  INTEGER,
    started_at  REAL,
    meta        TEXT
);
CREATE TABLE IF NOT EXISTS episodes (
    campaign_id TEXT,
    run_index   INTEGER,
    run_id      TEXT,
    payload     TEXT,
    PRIMARY KEY (campaign_id, run_index)
);
CREATE TABLE IF NOT EXISTS snapshots (
    campaign_id TEXT,
    run_index   INTEGER,
    closure     REAL,
    wclosure    REAL,
    cycles      REAL,
    sim_time_ns REAL,
    payload     TEXT,
    PRIMARY KEY (campaign_id, run_index)
);
CREATE TABLE IF NOT EXISTS bins (
    campaign_id TEXT,
    run_index   INTEGER,
    path        TEXT,
    grp         TEXT,
    coverpoint  TEXT,
    bin_name    TEXT,
    hits        INTEGER,
    goal        INTEGER,
    excluded    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_bins_campaign ON bins(campaign_id, path);
CREATE TABLE IF NOT EXISTS actions (
    campaign_id TEXT,
    run_index   INTEGER,
    step        INTEGER,
    payload     TEXT
);
"""


class CoverageStore:
    """Thin, dependency-free persistence layer for campaign history."""

    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------ basics
    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    def __enter__(self) -> "CoverageStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --------------------------------------------------------------- campaigns
    def begin_campaign(
        self,
        campaign_id: str,
        mode: str,
        algorithm: str,
        ai_enabled: bool,
        started_at: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO campaigns VALUES (?,?,?,?,?,?)",
            (campaign_id, mode, algorithm, int(ai_enabled), started_at, json.dumps(meta or {})),
        )
        self._conn.commit()

    def record_episode(self, campaign_id: str, run_index: int, payload: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO episodes VALUES (?,?,?,?)",
            (campaign_id, run_index, str(payload.get("run_id", "")), json.dumps(payload)),
        )
        self._conn.commit()

    def record_action(self, campaign_id: str, run_index: int, step: int, payload: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO actions VALUES (?,?,?,?)",
            (campaign_id, run_index, step, json.dumps(payload)),
        )
        self._conn.commit()

    def record_snapshot(
        self,
        campaign_id: str,
        run_index: int,
        snap: CoverageSnapshot,
        closure_value: float,
        weighted: float,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?)",
            (
                campaign_id,
                run_index,
                float(closure_value),
                float(weighted),
                float(snap.cycles),
                float(snap.sim_time_ns),
                json.dumps(snap.to_dict()),
            ),
        )
        rows = []
        for gname, g in snap.groups.items():
            for cpname, cp in g.coverpoints.items():
                for bname, b in cp.bins.items():
                    rows.append(
                        (
                            campaign_id,
                            run_index,
                            f"{gname}.{cpname}.{bname}",
                            gname,
                            cpname,
                            bname,
                            int(b.hits),
                            int(b.goal),
                            int(b.excluded),
                        )
                    )
        self._conn.execute("DELETE FROM bins WHERE campaign_id=? AND run_index=?", (campaign_id, run_index))
        self._conn.executemany("INSERT INTO bins VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self._conn.commit()

    # ------------------------------------------------------------------ queries
    def history(self, campaign_id: str) -> List[Tuple[int, float, float, float]]:
        """``[(run_index, closure, weighted_closure, cycles), ...]`` in run order."""
        cur = self._conn.execute(
            "SELECT run_index, closure, wclosure, cycles FROM snapshots "
            "WHERE campaign_id=? ORDER BY run_index",
            (campaign_id,),
        )
        return [(int(a), float(b), float(c), float(d)) for a, b, c, d in cur.fetchall()]

    def episodes(self, campaign_id: str) -> List[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT payload FROM episodes WHERE campaign_id=? ORDER BY run_index", (campaign_id,)
        )
        return [json.loads(r[0]) for r in cur.fetchall()]

    def latest_snapshot(self, campaign_id: str) -> Optional[CoverageSnapshot]:
        cur = self._conn.execute(
            "SELECT payload FROM snapshots WHERE campaign_id=? ORDER BY run_index DESC LIMIT 1",
            (campaign_id,),
        )
        row = cur.fetchone()
        return CoverageSnapshot.from_dict(json.loads(row[0])) if row else None

    def merged_snapshot(self, campaign_id: str) -> Optional[CoverageSnapshot]:
        """Union of every run in the campaign (hits = max over runs)."""
        cur = self._conn.execute(
            "SELECT grp, coverpoint, bin_name, MAX(hits), MAX(goal), MAX(excluded) "
            "FROM bins WHERE campaign_id=? GROUP BY grp, coverpoint, bin_name",
            (campaign_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return None
        snap = CoverageSnapshot(source=f"store:{campaign_id}")
        for grp, cp, bin_name, hits, goal, excluded in rows:
            snap.add_bin(
                grp,
                cp,
                Bin(name=bin_name, hits=int(hits or 0), goal=int(goal or 1), excluded=bool(excluded)),
            )
        return snap

    def hardest_bins(self, campaign_id: str, k: int = 20) -> List[Tuple[str, int]]:
        cur = self._conn.execute(
            "SELECT path, MAX(hits) AS h FROM bins WHERE campaign_id=? AND excluded=0 "
            "GROUP BY path ORDER BY h ASC, path ASC LIMIT ?",
            (campaign_id, k),
        )
        return [(r[0], int(r[1] or 0)) for r in cur.fetchall()]

    def campaigns(self) -> List[str]:
        cur = self._conn.execute("SELECT campaign_id FROM campaigns ORDER BY started_at")
        return [r[0] for r in cur.fetchall()]
