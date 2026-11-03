"""Short SQLite transactions; never hold a database lock during model calls."""

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from memory.contracts.errors import PendingAction


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class ArtifactJournal:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "artifacts.sqlite3"
        self._locks_guard = threading.Lock()
        self._operation_locks = {}
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, inputs TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS selections (
                    story TEXT, slot TEXT, artifact TEXT,
                    PRIMARY KEY(story, slot));
                CREATE TABLE IF NOT EXISTS publications (
                    story TEXT, slot TEXT, path TEXT, sha256 TEXT, artifact TEXT,
                    PRIMARY KEY(story, slot, path, sha256));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT, data TEXT, created REAL DEFAULT (julianday('now')));
                CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY, revision TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS story_revisions (
                    revision TEXT PRIMARY KEY, data TEXT);
                CREATE TABLE IF NOT EXISTS experiences (
                    id TEXT PRIMARY KEY, data TEXT);
            """
            )

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def begin(self, key, inputs):
        payload = encode(inputs)
        with self.transaction() as db:
            row = db.execute(
                "SELECT inputs,status,result FROM actions WHERE id=?", (key,)
            ).fetchone()
            if row:
                if row[0] != payload:
                    raise ValueError("Action id reused with changed inputs: " + key)
                if row[1] != "done":
                    raise PendingAction(
                        "Unresolved action; inspect receipt before retry: " + key
                    )
                return json.loads(row[2])
            db.execute(
                "INSERT INTO actions VALUES (?,?,?,NULL)", (key, payload, "started")
            )
            self.event(db, "action_started", {"id": key})

    def operation(self, key, inputs, function):
        """Coalesce same-process requests; unresolved cross-process work is pending.

        Only a per-key Python lock spans the call. Independent actions and other
        designs can continue; no SQLite transaction spans a model request.
        """
        with self._locks_guard:
            lock = self._operation_locks.setdefault(key, threading.RLock())
        waiting = time.monotonic()
        with lock:
            with self.transaction() as db:
                self.event(
                    db,
                    "resource_wait",
                    {"key": key, "elapsed_seconds": time.monotonic() - waiting},
                )
            cached = self.begin(key, inputs)
            if cached is not None:
                return cached
            with self.phase("operation", {"key": key}):
                result = function()
            self.finish(key, result)
            return result

    @contextmanager
    def phase(self, name, metadata=None):
        started, clock = time.time(), time.monotonic()
        try:
            yield
        finally:
            with self.transaction() as db:
                self.event(
                    db,
                    "phase",
                    {
                        "name": name,
                        "metadata": metadata or {},
                        "started_at": started,
                        "elapsed_seconds": time.monotonic() - clock,
                    },
                )

    def register_story(self, story_id, payload, activate=True):
        revision = digest([story_id, payload])
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO story_revisions VALUES (?,?)",
                (revision, encode(payload)),
            )
            if activate:
                db.execute(
                    "INSERT OR REPLACE INTO stories VALUES (?,?,?)",
                    (story_id, revision, encode(payload)),
                )
        return revision

    def story(self, story_id, revision=""):
        with self.transaction() as db:
            if revision:
                row = db.execute(
                    "SELECT revision,data FROM story_revisions WHERE revision=?",
                    (revision,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT revision,data FROM stories WHERE id=?", (story_id,)
                ).fetchone()
        if not row:
            return None
        data = json.loads(row[1])
        if digest([story_id, data]) != row[0]:
            raise ValueError("Story revision belongs to a different story")
        return dict(data, revision=row[0])

    def finish(self, key, result):
        with self.transaction() as db:
            db.execute(
                "UPDATE actions SET status='done',result=? WHERE id=?",
                (encode(result), key),
            )
            self.event(db, "action_finished", {"id": key})

    @staticmethod
    def event(db, kind, data):
        db.execute("INSERT INTO events(kind,data) VALUES (?,?)", (kind, encode(data)))

    def record(self, artifact):
        with self.transaction() as db:
            row = db.execute(
                "SELECT data FROM artifacts WHERE id=?", (artifact["id"],)
            ).fetchone()
            if row and row[0] != encode(artifact):
                raise ValueError("Immutable artifact changed")
            if not row:
                db.execute(
                    "INSERT INTO artifacts VALUES (?,?)",
                    (artifact["id"], encode(artifact)),
                )
                self.event(db, "artifact_created", artifact)

    def all_artifacts(self):
        with self.transaction() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM artifacts")]

    def publish(self, artifact, path):
        with self.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO publications VALUES (?,?,?,?,?)",
                (
                    artifact["story_id"],
                    artifact["slot"],
                    str(Path(path).resolve()),
                    artifact["sha256"],
                    artifact["id"],
                ),
            )

    def published(self, story, slot, path, sha):
        with self.transaction() as db:
            row = db.execute(
                "SELECT artifact FROM publications WHERE story=? AND slot=? AND path=? AND sha256=?",
                (story, slot, str(Path(path).resolve()), sha),
            ).fetchone()
        return row[0] if row else None

    def selected(self, story):
        with self.transaction() as db:
            rows = db.execute(
                "SELECT a.data FROM selections s JOIN artifacts a ON a.id=s.artifact WHERE s.story=?",
                (story,),
            )
            selected = [json.loads(r[0]) for r in rows]
            revision = db.execute(
                "SELECT revision FROM stories WHERE id=?", (story,)
            ).fetchone()
        ids = {a["id"] for a in selected}
        # A replaced dependency invalidates its consumers transitively. Preserve the
        # host selection, but exclude stale evidence from subsequent retrieval.
        stale = {
            a["id"]
            for a in selected
            if a.get("story_revision")
            and (not revision or a["story_revision"] != revision[0])
        }
        while True:
            new = {
                a["id"]
                for a in selected
                if any(d not in ids or d in stale for d in a.get("dependencies", []))
            }
            if new <= stale:
                break
            stale |= new
        return [dict(a, stale=a["id"] in stale) for a in selected]

    def select(self, story, slot, artifact_id):
        with self.transaction() as db:
            self._select(db, story, slot, artifact_id)

    def replace_selections(self, story, selections):
        """Atomically synchronize a complete authoritative host snapshot."""
        with self.transaction() as db:
            current = {
                r[0]
                for r in db.execute(
                    "SELECT slot FROM selections WHERE story=?", (story,)
                )
            }
            for slot in current | set(selections):
                self._select(db, story, slot, selections.get(slot))

    def _select(self, db, story, slot, artifact_id):
        if artifact_id:
            row = db.execute(
                "SELECT data FROM artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown artifact selection")
            a = json.loads(row[0])
            if (a["story_id"], a["slot"]) != (story, slot):
                raise ValueError("Selection crossed story or logical slot")
        row = db.execute(
            "SELECT artifact FROM selections WHERE story=? AND slot=?",
            (story, slot),
        ).fetchone()
        previous = row[0] if row else None
        if previous == artifact_id:
            return
        db.execute("DELETE FROM selections WHERE story=? AND slot=?", (story, slot))
        if artifact_id:
            db.execute(
                "INSERT INTO selections VALUES (?,?,?)", (story, slot, artifact_id)
            )
        self.event(
            db,
            "selection_changed",
            {
                "story": story,
                "slot": slot,
                "previous": previous,
                "selected": artifact_id,
            },
        )
