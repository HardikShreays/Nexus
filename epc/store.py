"""Phase 0 — structured store, knowledge graph (edges table) and hash-chained audit log.

ponytail: SQLite stands in for Aurora Postgres; same schema ports 1:1 (edges table = the
"lighter graph layer on Postgres" option from the plan). Swap the connect() call when the
portfolio outgrows one Lambda's /tmp. Audit rows mirror to DynamoDB when EPC_AUDIT_TABLE is
set — that is the immutable copy the plan asks for, outside the app's own write path.
Every read/write takes `project` — that is the tenant boundary, there is no cross-project query.
"""
import hashlib
import json
import sqlite3
import time

from . import aws

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (project TEXT, id TEXT, kind TEXT, data TEXT, PRIMARY KEY (project, id));
CREATE TABLE IF NOT EXISTS edges (project TEXT, src TEXT, rel TEXT, dst TEXT, UNIQUE (project, src, rel, dst));
CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, ts REAL, actor TEXT,
                                  action TEXT, payload TEXT, prev_hash TEXT, hash TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    # --- entities -------------------------------------------------------
    def put(self, project, kind, id, data):
        data = {**data, "id": id, "kind": kind}
        self.db.execute("INSERT OR REPLACE INTO entities VALUES (?,?,?,?)", (project, id, kind, json.dumps(data)))
        self.db.commit()
        return data

    def get(self, project, id):
        row = self.db.execute("SELECT data FROM entities WHERE project=? AND id=?", (project, id)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, project, id, **changes):
        cur = self.get(project, id)
        if cur is None:
            raise KeyError(f"{project}/{id} not found")
        return self.put(project, cur["kind"], id, {**cur, **changes})

    def find(self, project, kind, **where):
        rows = self.db.execute("SELECT data FROM entities WHERE project=? AND kind=? ORDER BY rowid", (project, kind))
        out = [json.loads(r[0]) for r in rows]
        return [e for e in out if all(e.get(k) == v for k, v in where.items())]

    def projects(self):
        return [r[0] for r in self.db.execute("SELECT DISTINCT project FROM entities ORDER BY project")]

    # --- graph ----------------------------------------------------------
    def link(self, project, src, rel, dst):
        self.db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?)", (project, src, rel, dst))
        self.db.commit()

    def neighbors(self, project, id, rel=None, reverse=False):
        a, b = ("dst", "src") if reverse else ("src", "dst")
        q = f"SELECT {b} FROM edges WHERE project=? AND {a}=?" + (" AND rel=?" if rel else "")
        return [r[0] for r in self.db.execute(q, (project, id, rel) if rel else (project, id))]

    # --- audit (tamper-evident: each row hashes the previous row) ----------
    def audit(self, project, actor, action, payload):
        prev = self.db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = prev[0] if prev else "genesis"
        ts = time.time()
        body = json.dumps(payload, sort_keys=True, default=str)
        h = hashlib.sha256(f"{prev}|{project}|{ts}|{actor}|{action}|{body}".encode()).hexdigest()
        cur = self.db.execute("INSERT INTO audit (project, ts, actor, action, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                              (project, ts, actor, action, body, prev, h))
        self.db.commit()
        aws.put_audit(project, cur.lastrowid, ts, actor, action, body, prev, h)
        return h

    def audit_log(self, project):
        rows = self.db.execute("SELECT seq, ts, actor, action, payload FROM audit WHERE project=? ORDER BY seq", (project,))
        return [{"seq": s, "ts": t, "actor": a, "action": ac, "payload": json.loads(p)} for s, t, a, ac, p in rows]

    def verify_audit(self):
        prev = "genesis"
        for project, ts, actor, action, body, prev_hash, h in self.db.execute(
                "SELECT project, ts, actor, action, payload, prev_hash, hash FROM audit ORDER BY seq"):
            expect = hashlib.sha256(f"{prev}|{project}|{ts}|{actor}|{action}|{body}".encode()).hexdigest()
            if prev_hash != prev or h != expect:
                return False
            prev = h
        return True
