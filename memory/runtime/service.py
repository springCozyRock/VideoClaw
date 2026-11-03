"""One pluggable Memory: A²RD schema, one controller, versioned asset storage."""
from dataclasses import asdict
from memory.runtime.controller import MemoryController
from memory.contracts.models import Segment, Reference
from memory.contracts.policy import Policy
from memory.assets.files import digest
from memory.assets.store import MemoryStore


class Memory:
    def __init__(self, directory, story_id="story", policy=None):
        self.directory, self.story_id = directory, story_id
        self.policy = policy or Policy(selection="strict")
        self.segments, self.references = None, None

    def register_story(self, segments, references=()):
        self.segments = [s if isinstance(s, Segment) else Segment(**s) for s in segments]
        self.references = [r if isinstance(r, Reference) else Reference(**r) for r in references]
        if not self.segments or len({s.id for s in self.segments}) != len(self.segments):
            raise ValueError("Story needs unique ordered segments")

    def plan(self, story, host, constraints=None, references=()):
        """Plan or revise unfinished shots without generating media."""
        from memory.narrative.planning import validate_plan
        with MemoryStore(self.directory, self.story_id) as store:
            previous = store.data.get("plan")
            completed = [r["segment"] for r in store.data.get("committed", [])]
            request = {"story": story, "constraints": constraints or {},
                       "previous_plan": previous, "completed": completed,
                       "goals": previous["goals"] if previous else [],
                       "actual_memory": store.snapshot()}
            from memory.harness.checks import ChainAudit
            from memory.contracts.errors import QualityBlocked
            previous_report = None
            for attempt in range(self.policy.chain_repairs + 1):
                plan = store.operation("plan/" + digest(request), request,
                    lambda: validate_plan(host.plan_story(request), request))
                if store.data.get("fingerprint") and digest(plan["segments"]) != digest(store.data.get("inputs", {}).get("segments")):
                    raise ValueError("Changing a bound execution plan requires an explicit story revision")
                report = ChainAudit(store, host).check("plan", {"plan": {"kind": "text", "content": plan}}, request)
                store.data.setdefault("plan_versions", {})[plan["revision_id"]] = plan
                if previous_report:
                    status = "verified" if report["status"] == "pass" else "unresolved"
                    repair = store.data.get("repairs", {}).get(previous_report["id"])
                    if repair:
                        repair.update(status=status, after_check=report["id"])
                    store.data.setdefault("repair_experiences", []).append({
                        "action": "revise_plan", "before_checks": [previous_report["id"]],
                        "after_check": report["id"], "outcome": status, "attribution_status": "hypothesis"})
                store.save()
                previous_report = report
                if report["status"] == "pass" or not hasattr(host, "check_chain"):
                    break
                if attempt == self.policy.chain_repairs:
                    raise QualityBlocked("Plan audit did not pass within the repair budget")
                request = dict(request, previous_plan=plan, goals=plan["goals"], defects=report,
                               repair_instruction="Correct failed criteria while preserving original user intent")
            store.data.setdefault("plan_versions", {})[plan["revision_id"]] = plan
            store.data["planning_request"] = request
            store.data["plan"] = plan
            store.save()
        self.register_story(plan["segments"], references)
        return plan

    def generate(self, host, progress=None, check_cancel=None):
        if self.segments is None:
            raise ValueError("Register the story before generation")
        from memory.harness.repair import RepairLoop
        from memory.harness.checks import ChainAudit
        from memory.contracts.errors import QualityBlocked
        with MemoryStore(self.directory, self.story_id) as store:
            # Persisted revised inputs are authoritative on resume.
            if store.data.get("repair_epoch"):
                self.segments = [Segment(**s) for s in store.data["inputs"]["segments"]]
                self.references = [Reference(**{k:v for k,v in r.items() if k != "media"})
                                   for r in store.data["inputs"]["references"]]
            loop = RepairLoop(store, host, self.policy)
            if store.data.get("pending_repair"):
                self.segments, self.references = loop.apply(self.segments, self.references, check_cancel)
            used = len(store.data.get("repair_runs", {}))
            while True:
                store.data["delivery"] = {"status": "pending"}
                store.save()
                store.data["active_failure_checks"] = []
                if check_cancel: check_cancel()
                try:
                    result = MemoryController(store, host, self.policy).run(
                        self.segments, self.references, progress, check_cancel)
                    if hasattr(host, "check_chain"):
                        sources = {r["segment"]["id"]: dict(r["video"], kind="video",
                            duration=r["segment"]["duration"], observation=r["observation"]) for r in result}
                        report = ChainAudit(store, host).check("sequence", sources, store.data.get("plan"))
                        loop.finish(report)
                        if report["status"] != "pass":
                            raise QualityBlocked("Sequence audit did not pass")
                    store.data["delivery"] = {"status": "passed" if hasattr(host, "check_chain") else "local_only",
                        "selection": digest([r["video"] for r in result])}
                    store.save()
                    store.export(store.root / "snapshot.json")
                    return result
                except QualityBlocked:
                    store.export(store.root / "snapshot.json")
                    if not hasattr(host, "plan_chain_repair") or used >= self.policy.chain_repairs:
                        raise
                    self.segments, self.references = loop.apply(self.segments, self.references, check_cancel)
                    used += 1

    def audit(self, host):
        """Cross-shot evidence audit; generates no new media."""
        from memory.harness.checks import ChainAudit
        with MemoryStore(self.directory, self.story_id) as store:
            records = store.data.get("committed", [])
            sources = {r["segment"]["id"]: dict(kind="video", duration=r["segment"]["duration"],
                **r["video"], observation=r["observation"]) for r in records}
            if not sources:
                raise ValueError("No selected videos to audit")
            report = ChainAudit(store, host).check("sequence", sources, store.data.get("plan"))
            store.export(store.root / "snapshot.json")
            return report

    def snapshot(self):
        with MemoryStore(self.directory, self.story_id) as store:
            return store.snapshot()

    def reselect(self, segment_id, revision_id):
        with MemoryStore(self.directory, self.story_id) as store:
            store.reselect(segment_id, revision_id)
            store.export(store.root / "snapshot.json")

    def select_candidate(self, segment_id, candidate_key, host):
        """Promote an already-observed alternative, without another generation."""
        with MemoryStore(self.directory, self.story_id) as store:
            candidate = store.data["candidates"][candidate_key]
            index = next(i for i,s in enumerate(store.data["inputs"]["segments"]) if s["id"] == segment_id)
            if not candidate_key.startswith(store.segment_key(index) + "/"):
                raise ValueError("Candidate belongs to an invalidated generation")
            definition = candidate["selection_context"]
            segment = Segment(**definition["segment"])
            if segment.id != segment_id:
                raise ValueError("Candidate belongs to a different segment")
            controller = MemoryController(store, host, self.policy)
            controller.evaluation.choose([candidate])
            index = next(i for i, s in enumerate(store.data["inputs"]["segments"]) if s["id"] == segment_id)
            # The candidate's context must still refer to the selected history.
            current = {r["segment"]["id"]: r for r in store.data["committed"]}
            for old in definition["context"]["history"]:
                if current.get(old["segment"]["id"], {}).get("video") != old["video"]:
                    raise ValueError("Candidate was generated against superseded history")
            revision = controller._commit(candidate_key + "/selection", index, segment,
                definition["context"], definition["frame"], definition["end"], candidate, select=False)
            store.reselect(segment_id, revision)
            store.export(store.root / "snapshot.json")
            return revision

    def revise_story(self, segments, references=()):
        """Explicitly invalidate old selections; preserve immutable revisions/assets."""
        self.register_story(segments, references)
        with MemoryStore(self.directory, self.story_id) as store:
            store.data = {"schema": 2, "operations": {}, "candidates": {}, "committed": [],
                          "story_revision": "pending-new-inputs"}
            store.save()

    def pending_publications(self):
        with MemoryStore(self.directory, self.story_id) as store:
            import json
            with store.journal.transaction() as db:
                return [dict(json.loads(data), event_id=id) for id, data in db.execute(
                    "SELECT id,data FROM outbox WHERE story=? AND acknowledged=0 ORDER BY rowid", (self.story_id,))]

    def acknowledge(self, event_id):
        with MemoryStore(self.directory, self.story_id) as store:
            with store.journal.transaction() as db:
                db.execute("UPDATE outbox SET acknowledged=1 WHERE id=? AND story=?", (event_id, self.story_id))
