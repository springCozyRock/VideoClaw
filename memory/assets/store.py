"""Single SQLite authority for A²RD memory and the asset/version journal.

The controller's working dictionaries are a materialized execution cache in this
same database. memory.json is never read or written by this store.
"""
import copy
import json
from pathlib import Path

from memory.assets.files import digest, media, verify_media
from memory.world.state import build_world_state
from memory.assets.journal import ArtifactJournal, encode
from memory.contracts.schema import SegmentMemory, textual_state


class ConcurrentSelection(RuntimeError):
    pass


class MemoryStore:
    def __init__(self, directory, story_id="story"):
        self.directory = Path(directory).resolve()
        self.root = self.directory
        self.journal = ArtifactJournal(self.directory)
        self.path = self.journal.path
        self.story_id = story_id
        self.lock = None
        with self.journal.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS execution (story TEXT PRIMARY KEY, epoch INTEGER, data TEXT);
                CREATE TABLE IF NOT EXISTS segment_versions (id TEXT PRIMARY KEY, story TEXT, segment TEXT, data TEXT, record TEXT);
                CREATE TABLE IF NOT EXISTS segment_selections (story TEXT, segment TEXT, revision TEXT, PRIMARY KEY(story,segment));
                CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, story TEXT, data TEXT, acknowledged INTEGER DEFAULT 0);
            """)

    def __enter__(self):
        self.lock = True  # No database/global lock spans provider calls.
        self.refresh()
        return self

    def __exit__(self, *args):
        self.lock = None

    def refresh(self):
        with self.journal.transaction() as db:
            row = db.execute("SELECT epoch,data FROM execution WHERE story=?", (self.story_id,)).fetchone()
        self.epoch = row[0] if row else 0
        self.data = json.loads(row[1]) if row else {
            "schema": 2, "operations": {}, "candidates": {}, "committed": [],
        }
        self._workspace()

    def _workspace(self):
        self.directory = (self.root / "revisions" / self.data["fingerprint"][:20]
                          if self.data.get("fingerprint") else self.root)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _write(self, db):
        row = db.execute("SELECT epoch FROM execution WHERE story=?", (self.story_id,)).fetchone()
        if (row[0] if row else 0) != self.epoch:
            raise ConcurrentSelection("Memory changed while this operation was running; refresh before continuing")
        self.epoch += 1
        db.execute("INSERT OR REPLACE INTO execution VALUES (?,?,?)", (self.story_id, self.epoch, encode(self.data)))
        for case in self.data.get("prompt_experiences", []):
            db.execute("INSERT OR IGNORE INTO experiences VALUES (?,?)", (digest(case), encode(case)))

    def save(self):
        if self.lock is None:
            raise RuntimeError("Use MemoryStore as a context manager")
        with self.journal.transaction() as db:
            self._write(db)

    def bind(self, inputs):
        if self.data.get("import_read_only"):
            raise ValueError("Legacy evidence is read-only; explicitly revise the story for new generation")
        fingerprint = digest([inputs, self.data["repair_epoch"]]) if self.data.get("repair_epoch") else digest(inputs)
        if self.data.get("fingerprint", fingerprint) != fingerprint:
            raise ValueError("Inputs changed; register a new story revision explicitly")
        self.data.update(fingerprint=fingerprint, inputs=inputs)
        self.data["story_revision"] = self.data.get("lineage_revision") or digest([self.story_id, inputs["segments"], inputs["references"]])
        self._workspace()
        self.save()

    def asset(self, item, slot, kind, role, operation_id="", parents=()):
        verify_media(item)
        aid = digest([self.story_id, self.data.get("story_revision"), slot, item["sha256"], operation_id, list(parents)])
        artifact = dict(
            id=aid, story_id=self.story_id, slot=slot, kind=kind, role=role,
            path=item["path"], sha256=item["sha256"], action_id=operation_id,
            origin="extracted" if role == "boundary" else "generated_or_imported",
            dependencies=list(parents), entities=[], position=None,
            observation={}, assessment={},
        )
        self.journal.record(artifact)
        return aid

    def operation(self, key, inputs, function):
        # Provider receipts are journaled before optimistic execution-cache writes.
        # If a concurrent selection invalidates the cache, the completed call is
        # still recoverable without another paid submission.
        namespace = self.data.get("fingerprint", "unbound")
        result = self.journal.operation(namespace + "/" + key, inputs, function)
        self.data["operations"][key] = {"inputs": copy.deepcopy(inputs), "result": result, "status": "done"}
        self.save()
        return result

    def candidate(self, key, value):
        if key in self.data["candidates"] and self.data["candidates"][key] != value:
            raise ValueError("Candidate changed: " + key)
        self.asset(value["media"], "candidate/" + key,
                   "video" if "/video/" in key else "image", "candidate", key)
        self.data["candidates"][key] = copy.deepcopy(value)
        self.save()

    def segment_key(self, index):
        # Invalidation increments the generation, preserving old operations/media.
        generation = self.data.get("generations", {}).get(str(index), 0)
        return "segment/" + str(index) + ("/revision-" + str(generation) if generation else "")

    def _version(self, record):
        sid = record["segment"]["id"]
        slot = "segment/" + sid
        op = record.get("candidate_key", digest(record["video"]))
        reference_ids = [self.asset(item, "reference/" + item["sha256"], "image", "design")
                         for item in record.get("reference_assets", [])]
        conditions = {k: self.asset(record[k], slot + "/" + k, "image", "condition", op)
                      for k in ("condition_frame", "condition_end") if record.get(k)}
        selected = {r["segment_id"]: r for r in self.selected(include_stale=True)}
        deps = {sid: selected[sid]["revision_id"] for sid in record["dependencies"]}
        parents = reference_ids + list(conditions.values()) + [selected[sid]["V"] for sid in deps]
        video = self.asset(record["video"], slot + "/video", "video", "actual", op, parents)
        frames = {k: self.asset(record[k], slot + "/" + k, "image", "boundary", op, [video]) for k in ("begin", "end")}
        # Inherited continuous boundaries are a real dependency even if retrieval
        # later changes its relevance-ranking strategy.
        revision = digest([self.data["story_revision"], record, deps])
        value = SegmentMemory(
            sid, revision, self.data["story_revision"], textual_state(record), frames, video,
            {"requested_mode": record.get("requested_mode", record["mode"]),
             "effective_mode": record["mode"], "conditions": conditions,
             "used_prompt": record["prompt"], "operation_id": op, "reference_asset_ids": reference_ids},
            {k: record.get(k) for k in ("review", "raw_review", "state_contract", "state_checks",
                                       "accepted", "quality_status", "event_assessment", "completed_goals", "unresolved_goals", "boundary_quality")},
            deps,
        ).to_dict()
        return value

    def commit(self, record):
        if record["index"] != len(self.data["committed"]):
            raise ValueError("Commit must extend valid selected prefix")
        value = self._version(record)
        self.data["committed"].append(copy.deepcopy(record))
        self.data["world_state"] = build_world_state(self.data["committed"])
        with self.journal.transaction() as db:
            self._write(db)
            db.execute("INSERT OR IGNORE INTO segment_versions VALUES (?,?,?,?,?)", (
                value["revision_id"], self.story_id, value["segment_id"], encode(value), encode(record)))
            db.execute("INSERT OR REPLACE INTO segment_selections VALUES (?,?,?)", (
                self.story_id, value["segment_id"], value["revision_id"]))
            self._enqueue(db, value)

    def archive(self, record):
        value = self._version(record)
        with self.journal.transaction() as db:
            self._write(db)
            db.execute("INSERT OR IGNORE INTO segment_versions VALUES (?,?,?,?,?)", (
                value["revision_id"], self.story_id, value["segment_id"], encode(value), encode(record)))
        return value["revision_id"]

    def _enqueue(self, db, value):
        event = {"segment_id": value["segment_id"], "revision_id": value["revision_id"],
                 "epoch": self.epoch, "video_asset_id": value["V"]}
        db.execute("INSERT OR IGNORE INTO outbox(id,story,data) VALUES (?,?,?)", (
            digest([self.story_id, event]), self.story_id, encode(event)))

    def selected(self, include_stale=False):
        with self.journal.transaction() as db:
            rows = db.execute("SELECT v.data FROM segment_selections s JOIN segment_versions v ON v.id=s.revision WHERE s.story=?", (self.story_id,)).fetchall()
        values = [json.loads(r[0]) for r in rows]
        values = self._mark_stale(values)
        return [r for r in values if include_stale or not r["stale"]]

    def _mark_stale(self, values):
        ids = {r["segment_id"]: r["revision_id"] for r in values}
        stale = {r["segment_id"] for r in values if r["story_revision"] != self.data.get("story_revision") or r["revision_id"] in self.data.get("invalidated_revisions", [])}
        while True:
            new = {r["segment_id"] for r in values if any(ids.get(s) != rev or s in stale for s, rev in r["dependencies"].items())}
            if new <= stale:
                break
            stale |= new
        return [dict(r, stale=r["segment_id"] in stale) for r in values]

    def reselect(self, segment_id, revision_id):
        with self.journal.transaction() as db:
            row = db.execute("SELECT data,record FROM segment_versions WHERE id=? AND story=? AND segment=?",
                             (revision_id, self.story_id, segment_id)).fetchone()
            if not row:
                raise ValueError("Unknown segment revision")
            value, record = map(json.loads, row)
            if value["story_revision"] != self.data["story_revision"]:
                raise ValueError("Cannot select a revision from an old storyline")
            if revision_id in self.data.get("invalidated_revisions", []):
                raise ValueError("Cannot select an invalidated revision")
            current = {s["id"]:s for s in self.data["inputs"]["segments"]}
            if digest(record["segment"]) != digest(current.get(segment_id)):
                raise ValueError("Revision does not match the current plan")
            current_rows = db.execute("SELECT v.data FROM segment_selections s JOIN segment_versions v ON v.id=s.revision WHERE s.story=?", (self.story_id,)).fetchall()
            selected = {v["segment_id"]: v for v in self._mark_stale([json.loads(row[0]) for row in current_rows])}
            if any(selected.get(sid, {}).get("revision_id") != rev or selected.get(sid, {}).get("stale", True)
                   for sid, rev in value["dependencies"].items()):
                raise ValueError("Cannot select a revision with stale dependencies")
            if not value["evaluation"].get("accepted"):
                raise ValueError("Cannot promote an unverified candidate as final selection")
            self.data["delivery"] = {"status": "pending"}
            db.execute("INSERT OR REPLACE INTO segment_selections VALUES (?,?,?)", (self.story_id, segment_id, revision_id))
            rows = db.execute("SELECT v.data,v.record FROM segment_selections s JOIN segment_versions v ON v.id=s.revision WHERE s.story=?", (self.story_id,)).fetchall()
            values = self._mark_stale([json.loads(r[0]) for r in rows])
            valid = {v["segment_id"]: v for v in values if not v["stale"]}
            by_id = {json.loads(r[0])["segment_id"]: json.loads(r[1]) for r in rows}
            records = []
            for segment in self.data["inputs"]["segments"]:
                if segment["id"] not in valid:
                    break
                records.append(by_id[segment["id"]])
            generations = self.data.setdefault("generations", {})
            for index in range(len(records), len(self.data["committed"])):
                generations[str(index)] = generations.get(str(index), 0) + 1
            self.data["committed"] = records
            self.data["world_state"] = build_world_state(records)
            self._write(db)
            self._enqueue(db, value)

    def rebuild_prefix(self):
        valid = {v["segment_id"]: v for v in self.selected()}
        records = []
        with self.journal.transaction() as db:
            for segment in self.data["inputs"]["segments"]:
                value = valid.get(segment["id"])
                if not value:
                    break
                row = db.execute("SELECT record FROM segment_versions WHERE id=?", (value["revision_id"],)).fetchone()
                records.append(json.loads(row[0]))
        previous = self.data["committed"]
        self.data["committed"] = records
        self.data["world_state"] = build_world_state(records)
        generations = self.data.setdefault("generations", {})
        for index in range(len(records), len(previous)):
            generations[str(index)] = generations.get(str(index), 0) + 1
        self.save()

    def revise_execution(self, segments, references, start):
        """Invalidate a conservative suffix, preserving immutable versions and prefix."""
        from dataclasses import asdict
        if not 0 <= start <= len(self.data["committed"]):
            raise ValueError("Invalid repair boundary")
        new_segments = json.loads(json.dumps([asdict(s) for s in segments]))
        if new_segments[:start] != json.loads(json.dumps(self.data["inputs"]["segments"][:start])):
            raise ValueError("Repair changes a protected prefix")
        self.data["delivery"] = {"status": "pending"}
        self.data.setdefault("execution_versions", []).append(copy.deepcopy(self.data["inputs"]))
        invalid = self.data.setdefault("invalidated_revisions", [])
        prefix = {r["segment"]["id"] for r in self.data["committed"][:start]}
        invalid.extend(v["revision_id"] for v in self.selected(True) if v["segment_id"] not in prefix)
        self.data["lineage_revision"] = self.data["story_revision"]
        generations = self.data.setdefault("generations", {})
        for index in range(start, len(new_segments)):
            generations[str(index)] = generations.get(str(index), 0) + 1
        self.data["committed"] = self.data["committed"][:start]
        self.data["world_state"] = build_world_state(self.data["committed"])
        inputs = copy.deepcopy(self.data["inputs"])
        inputs["segments"] = new_segments
        inputs["references"] = [dict(asdict(r), media=media(r.path)) for r in references]
        inputs["seeds"] = {s.id: media(s.seed_frame) for s in segments if s.seed_frame}
        # Salt even unchanged inputs so a retry cannot reuse failed provider results.
        self.data["repair_epoch"] = self.data.get("repair_epoch", 0) + 1
        self.data["inputs"] = inputs
        self.data.pop("fingerprint", None)
        self.data["operations"] = {}
        for key in ("appearance_plan", "appearance_references", "global_reference_graph", "reference_reuse_source"):
            self.data.pop(key, None)
        self.save()

    def snapshot(self):
        references = list(self.data.get("appearance_references", {}).values())
        references += self.data.get("global_reference_graph", {}).get("resolved", [])
        refs = []
        for ref in references:
            item = ref.get("media")
            if item:
                aid = self.asset(item, "reference/" + ref["id"], "image", "design")
                refs.append(dict(ref, asset_id=aid))
        return {"schema": "aard.memory/2", "story_id": self.story_id,
                "story_revision": self.data.get("story_revision"),
                "storyline": self.data.get("inputs", {}).get("segments", []),
                "delivery": self.data.get("delivery", {"status": "pending"}),
                "Checks": self.data.get("checks", {}),
                "Repairs": self.data.get("repairs", {}),
                "repair_runs": self.data.get("repair_runs", {}),
                "repair_experiences": self.data.get("repair_experiences", []),
                "Plan": self.data.get("plan"),
                "plan_versions": self.data.get("plan_versions", {}),
                "M": self.selected(include_stale=True),
                "R": {"references": refs, "appearance_plan": self.data.get("appearance_plan"),
                      "graph": self.data.get("global_reference_graph")},
                "D": self.data.get("prompt_experiences", []),
                "world_state": self.data.get("world_state", {})}

    def export(self, path):
        Path(path).write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2))
