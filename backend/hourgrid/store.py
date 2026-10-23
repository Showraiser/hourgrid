"""SQLite persistence (thread-safe, single file)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS intervals (
  id INTEGER PRIMARY KEY, start_ts TEXT, period TEXT, clearing_price INTEGER, volume_wh INTEGER,
  scheduled_wh INTEGER, n_bids INTEGER, n_asks INTEGER, n_fills INTEGER, orderbook_hash TEXT,
  fills_root TEXT, ghi REAL, temp REAL, grid_price INTEGER, floor INTEGER, ceiling INTEGER,
  battery_soc REAL, status TEXT, commit_tx TEXT, settle_tx TEXT, error TEXT, curves TEXT, totals TEXT,
  ref_price INTEGER, period_label TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  interval_id INTEGER, agent TEXT, side TEXT, wh INTEGER, price INTEGER, reason TEXT
);
CREATE TABLE IF NOT EXISTS fills (
  interval_id INTEGER, idx INTEGER, seller TEXT, buyer TEXT, wh INTEGER, scheduled_wh INTEGER,
  price INTEGER, cert_id TEXT, status TEXT, PRIMARY KEY (interval_id, idx)
);
CREATE TABLE IF NOT EXISTS readings (
  interval_id INTEGER, home_id TEXT, gen_wh REAL, load_wh REAL, export_wh INTEGER, import_wh INTEGER,
  gen_fc REAL, load_fc REAL, max_plausible_wh REAL, anomaly_score REAL, accepted INTEGER,
  tampered INTEGER, signature TEXT, PRIMARY KEY (interval_id, home_id)
);
CREATE TABLE IF NOT EXISTS certificates (
  cert_id TEXT PRIMARY KEY, meter_id TEXT, home_id TEXT, hour_start TEXT, zone TEXT,
  minted_wh INTEGER DEFAULT 0, retired_wh INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS holdings (
  cert_id TEXT, home_id TEXT, wh INTEGER, PRIMARY KEY (cert_id, home_id)
);
CREATE TABLE IF NOT EXISTS retirements (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cert_id TEXT, home_id TEXT, wh INTEGER, beneficiary TEXT,
  ts TEXT, tx TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS balances (
  home_id TEXT PRIMARY KEY, escrow INTEGER, earned INTEGER DEFAULT 0, spent INTEGER DEFAULT 0,
  sold_wh INTEGER DEFAULT 0, bought_wh INTEGER DEFAULT 0, points INTEGER DEFAULT 0,
  netmeter_value INTEGER DEFAULT 0, grid_cost_avoided INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, sim_ts TEXT, level TEXT, kind TEXT, message TEXT,
  interval_id INTEGER, home_id TEXT
);
CREATE TABLE IF NOT EXISTS agent_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, home_id TEXT, instruction TEXT, prefs TEXT,
  explanation TEXT, engine TEXT
);
CREATE INDEX IF NOT EXISTS ix_fills_buyer ON fills(buyer);
CREATE INDEX IF NOT EXISTS ix_fills_seller ON fills(seller);
CREATE INDEX IF NOT EXISTS ix_orders_iv ON orders(interval_id);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        for col in ("ref_price INTEGER", "period_label TEXT"):  # upgrade older databases
            try:
                self.conn.execute(f"ALTER TABLE intervals ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass

    def reset(self) -> None:
        with self.lock:
            for t in ["intervals", "orders", "fills", "readings", "certificates", "holdings",
                      "retirements", "balances", "alerts", "agent_log"]:
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.commit()

    def execute(self, sql: str, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def executemany(self, sql: str, rows):
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    def all(self, sql: str, params=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, params).fetchone()
            return dict(r) if r else None

    def alert(self, level: str, kind: str, message: str, sim_ts=None, interval_id=None, home_id=None):
        from datetime import datetime
        self.execute(
            "INSERT INTO alerts(ts, sim_ts, level, kind, message, interval_id, home_id) VALUES (?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), sim_ts, level, kind, message, interval_id, home_id),
        )


def dumps(x) -> str:
    return json.dumps(x, separators=(",", ":"), default=str)
