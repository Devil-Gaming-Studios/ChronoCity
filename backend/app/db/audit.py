"""Persistent local audit journal. No retention cap and no raw credentials/headers.

SQLite is deliberately separate from optional telemetry PostgreSQL so the offline
demo also retains history. Transactions are serialized; storage errors propagate.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class AuditStore:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.runtime_id = uuid.uuid4().hex
        self.city = ""
        with self.connection:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL, runtime_id TEXT NOT NULL, city TEXT NOT NULL,
                    kind TEXT NOT NULL, scope TEXT NOT NULL, actor TEXT NOT NULL,
                    plan_id TEXT NOT NULL, summary TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_kind_id ON audit_events(kind, id);
                CREATE INDEX IF NOT EXISTS audit_plan_id ON audit_events(plan_id, id);
                CREATE TABLE IF NOT EXISTS audit_plans (
                    runtime_id TEXT NOT NULL, plan_id TEXT NOT NULL,
                    updated REAL NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(runtime_id, plan_id)
                );
            """)

    def record(self, kind: str, payload: dict[str, Any], *, scope: str = "live",
               actor: str = "system", summary: str = "") -> None:
        encoded = json.dumps(payload, default=str, ensure_ascii=False)
        plan = payload.get("plan") if kind == "plan_snapshot" else None
        plan_id = str(payload.get("plan_id") or (plan or {}).get("id", ""))
        text = summary or str(payload.get("answer") or payload.get("detail")
                              or payload.get("title") or payload.get("stage") or kind.replace("_", " "))
        now = time.time()
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO audit_events(ts,runtime_id,city,kind,scope,actor,plan_id,summary,payload) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (now, self.runtime_id, self.city, kind, scope, actor, plan_id, text, encoded),
            )
            if plan:
                self.connection.execute(
                    "INSERT INTO audit_plans VALUES(?,?,?,?) ON CONFLICT(runtime_id,plan_id) "
                    "DO UPDATE SET updated=excluded.updated,payload=excluded.payload",
                    (self.runtime_id, plan_id, now, json.dumps(plan, default=str)),
                )

    def page(self, *, before: int | None = None, limit: int = 50,
             kind: str = "", scope: str = "", plan_id: str = "") -> dict[str, Any]:
        clauses, args = [], []
        for column, value in (("kind", kind), ("scope", scope), ("plan_id", plan_id)):
            if value:
                clauses.append(f"{column} = ?")
                args.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.lock:
            total = self.connection.execute("SELECT COUNT(*) FROM audit_events" + where, args).fetchone()[0]
            if before is not None:
                clauses.append("id < ?")
                args.append(before)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = self.connection.execute(
                "SELECT * FROM audit_events" + where + " ORDER BY id DESC LIMIT ?", [*args, limit + 1],
            ).fetchall()
            kinds = [row[0] for row in self.connection.execute("SELECT DISTINCT kind FROM audit_events ORDER BY kind")]
        items = [{**dict(row), "payload": json.loads(row["payload"])} for row in rows[:limit]]
        return {"items": items, "total": total, "next_before": items[-1]["id"] if len(rows) > limit else None,
                "kinds": kinds, "storage": "sqlite", "runtime_id": self.runtime_id}

    def plans(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM audit_plans ORDER BY updated DESC LIMIT ? OFFSET ?", (limit, offset),
            ).fetchall()
            total = self.connection.execute("SELECT COUNT(*) FROM audit_plans").fetchone()[0]
        return {"items": [{"runtime_id": row["runtime_id"], "updated": row["updated"],
                           "plan": json.loads(row["payload"])} for row in rows], "total": total}

    def current_plans(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT payload FROM audit_plans WHERE runtime_id=? ORDER BY updated DESC", (self.runtime_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self) -> None:
        with self.lock:
            self.connection.close()


def record(app: Any, kind: str, payload: dict[str, Any], **kwargs: Any) -> None:
    store = getattr(app.state, "audit", None)
    if store is not None:
        store.record(kind, payload, **kwargs)
