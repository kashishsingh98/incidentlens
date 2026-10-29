"""Real SQLite workload and append-only lab telemetry. No artificial sleep latency."""

import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

QUERY = "SELECT count(*), sum(total) FROM orders WHERE customer_id = ?"
INDEX = "idx_orders_customer"


def db_path() -> Path:
    return Path(os.environ.get("INCIDENTLENS_DB", "data/lab.db")).resolve()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def connection(path: Path | None = None, *, readonly: bool = False):
    path = path or db_path()
    if readonly:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()


def initialize(path: Path | None = None, rows: int = 150_000) -> None:
    with connection(path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, total INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, experiment TEXT NOT NULL,
                ts TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_experiment ON events(experiment, id);
        """)
        if c.execute("SELECT count(*) FROM orders").fetchone()[0] == 0:
            c.executemany(
                "INSERT INTO orders VALUES (?, ?, ?)",
                ((i, i % 10_000, (i * 17) % 5000) for i in range(rows)),
            )
            c.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON orders(customer_id)")


def event(c, experiment: str, kind: str, payload: dict) -> None:
    c.execute(
        "INSERT INTO events(experiment, ts, kind, payload) VALUES (?, ?, ?, ?)",
        (experiment, now(), kind, json.dumps(payload)),
    )


def benchmark(c, experiment: str, phase: str, samples: int = 30) -> None:
    # Warm the connection/cache before measurement. Both phases use identical queries.
    for customer in range(3):
        c.execute(QUERY, (customer,)).fetchone()
    for customer in range(samples):
        start = time.perf_counter_ns()
        result = c.execute(QUERY, (customer,)).fetchone()
        duration_ms = (time.perf_counter_ns() - start) / 1_000_000
        event(
            c,
            experiment,
            "request",
            {
                "phase": phase,
                "duration_ms": round(duration_ms, 6),
                "customer_id": customer,
                "matched_orders": result[0],
                "status": 200,
                "service": "orders-api",
            },
        )


def baseline(path: Path | None = None) -> dict:
    initialize(path)
    experiment = str(uuid.uuid4())
    with connection(path) as c:
        c.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON orders(customer_id)")
        c.execute("INSERT INTO experiments VALUES (?, ?)", (experiment, now()))
        event(
            c,
            experiment,
            "deployment",
            {
                "version": "v1.0",
                "action": "baseline",
                "change": "Customer index present",
                "sql": f"CREATE INDEX {INDEX} ON orders(customer_id)",
            },
        )
        benchmark(c, experiment, "baseline")
    return {"experiment_id": experiment, "phase": "baseline"}


def phase_of(experiment: str, path: Path | None = None) -> str:
    deployments = read_events(experiment, "deployment", path)
    if not deployments:
        raise ValueError("Unknown experiment. Start a baseline first.")
    return deployments[-1]["action"]


def change_index(experiment: str, *, restore: bool, path: Path | None = None) -> dict:
    current = phase_of(experiment, path)
    expected = "incident" if restore else "baseline"
    if current != expected:
        raise ValueError(f"Expected {expected} phase; current phase is {current}.")
    with connection(path) as c:
        if restore:
            c.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON orders(customer_id)")
        else:
            c.execute(f"DROP INDEX IF EXISTS {INDEX}")
        phase = "recovery" if restore else "incident"
        event(
            c,
            experiment,
            "deployment",
            {
                "version": "v1.2" if restore else "v1.1",
                "action": phase,
                "change": "Restore customer index" if restore else "Remove customer index",
                "sql": f"CREATE INDEX {INDEX} ON orders(customer_id)"
                if restore
                else f"DROP INDEX {INDEX}",
            },
        )
        benchmark(c, experiment, phase)
        # Persist the plan at the time of this phase; later recovery cannot rewrite history.
        plan = [r[3] for r in c.execute("EXPLAIN QUERY PLAN " + QUERY, (42,))]
        event(c, experiment, "query_plan", {"phase": phase, "query": QUERY, "plan": plan})
    return {"experiment_id": experiment, "phase": phase}


def read_events(experiment: str, kind: str | None = None, path: Path | None = None) -> list:
    with connection(path, readonly=True) as c:
        sql = "SELECT * FROM events WHERE experiment = ?"
        params = [experiment]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        return [
            {
                "event_id": r["id"],
                "timestamp": r["ts"],
                "kind": r["kind"],
                **json.loads(r["payload"]),
            }
            for r in c.execute(sql + " ORDER BY id", params)
        ]


def metrics(experiment: str, path: Path | None = None) -> dict:
    requests = read_events(experiment, "request", path)
    phases = {}
    for phase in ("baseline", "incident", "recovery"):
        points = [r for r in requests if r["phase"] == phase]
        if not points:
            continue
        values = sorted(r["duration_ms"] for r in points)
        phases[phase] = {
            "samples": len(values),
            "p95_ms": values[math.ceil(len(values) * 0.95) - 1],
            "mean_ms": round(sum(values) / len(values), 6),
            "first_event": points[0]["event_id"],
            "last_event": points[-1]["event_id"],
        }
    return {"experiment_id": experiment, "phases": phases, "points": requests}


def latest(path: Path | None = None) -> str | None:
    with connection(path, readonly=True) as c:
        row = c.execute("SELECT id FROM experiments ORDER BY rowid DESC LIMIT 1").fetchone()
        return row[0] if row else None
