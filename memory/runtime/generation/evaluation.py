"""Observe actual media, verify state evidence, and select bounded candidates."""

import copy
import json
from pathlib import Path
from memory.contracts.errors import QualityBlocked
from memory.contracts.models import accepted, average
from memory.world.state import slots, evaluate, constrain_review, conservative_facts
from memory.assets.files import media, verify_media


class CandidateEvaluation:
    def __init__(self, store, backend, policy):
        self.store, self.backend, self.policy = store, backend, policy

    def boundaries(self, key, asset):
        result = self.store.operation(
            key,
            asset,
            lambda: [
                media(p)
                for p in self.backend.boundaries(
                    asset["path"],
                    self.store.directory / "boundaries" / key.replace("/", "-"),
                )
            ],
        )
        for item in result:
            verify_media(item)
        return result

    def evaluate(self, kind, op, asset, segment, request):
        self.store.data["active_failure_checks"] = []
        receipt = Path(asset["path"] + ".receipt.json")
        if receipt.exists():
            request = dict(request, prompt=json.loads(receipt.read_text())["used_prompt"])
        if kind == "video" and self.policy.hierarchical_observation:
            # Observe the actual generated beginning, not the intended condition
            # image: the generator may alter the condition at its first frame.
            bounds = self.boundaries(op + "/observation_bounds", asset)
            initial = self.store.operation(
                op + "/observe_actual_begin",
                {"asset": bounds[0], "kind": "frame"},
                lambda: self.backend.observe("frame", bounds[0]["path"], segment),
            )
            observation = self.store.operation(
                op + "/observe",
                {
                    "asset": asset,
                    "kind": kind,
                    "actual_begin": bounds[0],
                    "initial_observation": initial,
                },
                lambda: self.backend.observe_with_begin(
                    asset["path"], segment, bounds[0], initial
                ),
            )
        else:
            observation = self.store.operation(
                op + "/observe",
                {"asset": asset, "kind": kind},
                lambda: self.backend.observe(kind, asset["path"], segment),
            )
        review = self.store.operation(
            op + "/review",
            {"asset": asset, "observation": observation, "request": request},
            lambda: self.backend.review(kind, asset["path"], observation, request),
        )
        candidate = {
            "media": asset,
            "observation": observation,
            "review": review,
            "prompt": request["prompt"],
            "accepted": accepted(review, self.policy),
        }
        contract = request["context"]["state_contract"]
        requested = slots(contract, kind, request["context"].get("frame_role", "begin"))
        bounds = (
            self.boundaries(op + "/observation_bounds", asset)
            if kind == "video"
            else None
        )
        observation = self.inspect_states(
            kind,
            op,
            asset,
            requested,
            segment,
            request["context"]["references"],
            bounds,
        )
        checks = evaluate(contract, observation, requested)
        raw = copy.deepcopy(candidate["review"])
        candidate.update(
            raw_review=raw,
            state_observation=observation,
            state_checks=checks,
            review=constrain_review(raw, checks),
        )
        candidate["accepted"] = accepted(candidate["review"], self.policy)
        from memory.harness.checks import ChainAudit
        sources = {"candidate": dict(asset, kind=kind, duration=segment.duration,
                                     observation=candidate["observation"], role="candidate")}
        if kind == "frame":
            for ref in request["context"].get("references", []):
                sources["reference/" + ref["id"]] = dict(ref["media"], kind="frame", role="identity_anchor")
        audit = ChainAudit(self.store, self.backend)
        report = audit.check(kind, sources, {"segment": request.get("segment"),
                                            "contract": contract, "prompt": request["prompt"]})
        reports = [report]
        beat = next((b for b in self.store.data.get("plan", {}).get("beats", []) if b["segment_id"] == segment.id), None)
        if kind == "video" and beat:
            event = audit.check("event", sources, beat)
            candidate["event_assessment"] = {"beat": beat, "check_id": event["id"], "status": event["status"]}
            reports.append(event)
        if kind == "video" and request["context"].get("history"):
            for record in request["context"]["history"]:
                sources["history/" + record["segment"]["id"]] = dict(
                    record["video"], kind="video", duration=record["segment"]["duration"],
                    observation=record["observation"])
            reports.append(audit.check("sequence", sources, request["context"]["segment"]))
        candidate["chain_checks"] = [r["id"] for r in reports]
        failures = [c.get("defect", c["criterion"]) for r in reports for c in r["checks"] if c["status"] == "fail"]
        unknown_required = any(r["status"] == "unknown" for r in reports) and hasattr(self.backend, "check_chain")
        if unknown_required:
            failures.append("Required chain evidence remains unknown")
        if failures:
            candidate["review"]["hard_failures"].extend(failures)
            candidate["accepted"] = False
        return candidate

    def inspect_states(
        self, kind, op, asset, requested, segment, references, bounds=None
    ):
        if not requested:
            return {"facts": []}
        if kind == "frame":
            return self.store.operation(
                op + "/inspect_state",
                {
                    "asset": asset,
                    "kind": kind,
                    "slots": requested,
                    "references": references,
                },
                lambda: self.backend.inspect_state(
                    kind, asset["path"], requested, segment, references
                ),
            )
        facts = []
        for phase, index in (("end", 1), ("begin", 0)):
            phase_slots = [s for s in requested if s["phase"] == phase]
            if not phase_slots:
                continue
            # A video narrative must not substitute for looking at each actual boundary.
            boundary = self.store.operation(
                op + "/inspect_state/" + phase,
                {
                    "asset": bounds[index],
                    "slots": phase_slots,
                    "references": references,
                },
                lambda: self.backend.inspect_state(
                    "frame", bounds[index]["path"], phase_slots, segment, references
                ),
            )
            for original in boundary["facts"]:
                fact = copy.deepcopy(original)
                fact["boundary_evidence"] = {
                    "media": bounds[index],
                    "frame_evidence": copy.deepcopy(fact["evidence"]),
                    "mapping": "Actual decoded "
                    + phase
                    + " image; timeline boundary label, not exact frame PTS",
                }
                timestamp = segment.duration if phase == "end" else 0
                for evidence in fact["evidence"]:
                    evidence.update(start=timestamp, end=timestamp)
                facts.append(fact)
        interval_slots = [s for s in requested if s["phase"] == "throughout"]
        if interval_slots:
            observed = self.store.operation(
                op + "/inspect_state/interval",
                {
                    "asset": asset,
                    "slots": interval_slots,
                    "references": references,
                    "actual_bounds": bounds,
                },
                lambda: self.backend.inspect_state(
                    "video", asset["path"], interval_slots, segment, references, bounds
                ),
            )
            facts.extend(copy.deepcopy(observed["facts"]))
        return conservative_facts({"facts": facts}, requested, segment.duration)

    def choose(self, candidates):
        verified = [
            c
            for c in candidates
            if c.get("state_checks", {}).get("critical_passed", False)
        ]
        if self.policy.critical_state_gate and not verified:
            raise QualityBlocked(
                "Critical visual state remains failed/uncertain after the fixed candidate budget"
            )
        candidates = verified or candidates
        if self.policy.selection == "strict":
            candidates = [c for c in candidates if c["accepted"]]
        if not candidates:
            raise QualityBlocked("No selectable candidate under the configured policy")
        return max(candidates, key=lambda c: average(c["review"]))
