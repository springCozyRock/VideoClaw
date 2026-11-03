"""One autoregressive pipeline: plan, retrieve, generate, verify, then commit."""

import copy
from dataclasses import asdict
from memory.contracts.policy import Policy
from memory.contracts.models import Segment
from memory.assets.files import media, verify_media, digest
from memory.contracts.validation import validate_decision
from memory.world.state import build_world_state, compact_world, persistent_requirements, inherit_requirements
from memory.world.references.manager import ReferenceMemory
from memory.world.references.shots import extract_shot_ends
from memory.assets.retrieval import ContextRetrieval
from memory.runtime.generation.candidates import CandidateGenerator
from memory.runtime.generation.evaluation import CandidateEvaluation
from memory.harness.optimization.optimizer import PromptOptimizer
from memory.harness.optimization.semantic import ExperienceRepository


class MemoryController:
    implementation = "long-video-memory"

    def __init__(self, store, backend, policy=None):
        self.store, self.backend = store, backend
        self.policy = policy or Policy()
        self.references = ReferenceMemory(store, backend, self.policy)
        self.retrieval = ContextRetrieval(store, backend, self.policy)
        self.evaluation = CandidateEvaluation(store, backend, self.policy)
        self.optimizer = PromptOptimizer(store, backend, self.policy)
        self.generation = CandidateGenerator(
            store,
            backend,
            self.policy,
            self.references,
            self.evaluation,
            self.optimizer,
        )

    def run(self, segments, references=(), progress=None, check_cancel=None):
        segments = list(segments)
        if not segments or len({s.id for s in segments}) != len(segments):
            raise ValueError("Unique nonempty segments required")
        refs, records, known = self._initialize(segments, references, check_cancel)
        for index, segment in enumerate(segments):
            if check_cancel:
                check_cancel()
            if index < len(records):
                if progress:
                    progress(records[index])
                continue
            self._check_event_dependencies(segment, records)
            key = (self.store.segment_key(index) if hasattr(self.store, "segment_key")
                   else "segment/" + str(index))
            ledger = build_world_state(records)
            context = self._prepare_context(
                key, index, segments, records, refs, ledger, known
            )
            image_refs = self.retrieval.images(context)
            inherited = context["decision"]["continuous"]
            seed = records[-1]["end"]["path"] if inherited else segment.seed_frame
            frame = self.generation.frame(
                segment,
                context,
                key + "/begin",
                seed,
                image_refs,
                inherited,
                check_cancel,
            )
            context.update(
                begin_media=frame["media"], begin_observation=frame["observation"]
            )
            end = None
            if context["requested_mode"] == "interpolation":
                end = self._plan_end(
                    key,
                    segment,
                    context,
                    records,
                    refs,
                    ledger,
                    frame,
                    image_refs,
                    check_cancel,
                )
            video = self.generation.video(
                segment, context, key, frame, end, image_refs, check_cancel
            )
            record = self._commit(key, index, segment, context, frame, end, video)
            if progress:
                progress(record)
        return list(records)

    def _check_event_dependencies(self, segment, records):
        from memory.narrative.events import check_event_dependencies
        check_event_dependencies(self.store.data.get("plan"), segment, records)

    def _initialize(self, segments, references, check_cancel):
        original = [dict(asdict(r), media=media(r.path)) for r in references]
        self.store.bind(
            {
                "segments": [asdict(s) for s in segments],
                "references": original,
                "seeds": {s.id: media(s.seed_frame) for s in segments if s.seed_frame},
                "policy": asdict(self.policy),
                "backend": self.backend.identity(),
                "implementation": self.implementation,
            }
        )
        self.store.data.setdefault("prompt_experiences", [])
        if "seed_experiences" not in self.store.data:
            repo = self.policy.experience_repository
            self.store.data["seed_experiences"] = (
                ExperienceRepository(repo).snapshot(
                    digest([asdict(s) for s in segments])
                )
                if repo
                else []
            )
            self.store.save()
        refs = self.references.initialize(segments, original, check_cancel)
        records = self.store.data["committed"]
        for r in records:
            for k in ("video", "begin", "end"):
                verify_media(r[k])
        known = sorted(
            {v for s in segments for v in s.entities + s.locations}
            | {v for r in refs for v in r["entities"] + r["locations"]}
        )
        return refs, records, known

    def _prepare_context(self, key, index, segments, records, refs, ledger, known):
        segment = segments[index]
        context = {
            "segment": asdict(segment),
            "next_segment": (
                asdict(segments[index + 1]) if index + 1 < len(segments) else None
            ),
            "history": records[-1:],
            "references": [],
            "storyline": [asdict(s) for s in segments],
            "previous_segment_id": (records[-1]["segment"]["id"] if records else None),
            "known_entities": known,
            "repair_feedback": [r["route"] for r in self.store.data.get("repair_runs", {}).values() if r["status"] == "applied"],
            "world_state": compact_world(ledger),
            "persistent_requirements": persistent_requirements(records),
        }
        decision = self.store.operation(
            key + "/prepare", context, lambda: self.backend.prepare(context)
        )
        validate_decision(decision, bool(records))
        for k in ("no_new_environment", "next_contiguous"):
            if type(decision.get(k)) is not bool:
                raise ValueError("Adaptive conditions required")
        mode = (
            "extrapolation"
            if decision["no_new_environment"]
            and (context["next_segment"] is None or decision["next_contiguous"])
            else "interpolation"
        )
        if not self.policy.adaptive:
            mode = "extrapolation"
        if (
            mode == "interpolation"
            and not self.backend.identity()["capabilities"]["last_frame"]
        ):
            raise ValueError("Backend does not support last frame")
        history, current_refs = self.retrieval.retrieve(
            key + "/retrieve", segment, records, refs, ledger
        )
        context.update(history=history, references=current_refs, requested_mode=mode)
        context = self.references.bind_context(context)
        contract = self.store.operation(
            key + "/state_contract",
            {"context": context, "decision": decision},
            lambda: self.backend.prepare_state_contract(context, decision),
        )
        contract = inherit_requirements(
            contract, context["persistent_requirements"], segment.entities
        )
        context.update(
            decision=decision,
            state_contract=contract,
            requested_mode=mode,
            frame_role="begin",
        )
        return context

    def _plan_end(
        self,
        key,
        segment,
        context,
        records,
        refs,
        ledger,
        frame,
        image_refs,
        check_cancel,
    ):
        next_context = None
        end_refs = image_refs
        end_prompt = context["decision"]["end_frame_prompt"]
        historical_seed = ""
        if context["next_segment"]:
            next_segment = Segment(**context["next_segment"])
            next_history, next_refs = self.retrieval.retrieve(
                key + "/retrieve_next", next_segment, records, refs, ledger
            )
            next_context = {
                "segment": asdict(next_segment),
                "history": next_history,
                "references": next_refs,
                "world_state": compact_world(ledger),
            }
            next_context = self.references.bind_context(next_context)
            boundary = self.store.operation(
                key + "/next_boundary",
                {"context": context, "next_context": next_context},
                lambda: self.backend.prepare_next_boundary(context, next_context),
            )
            end_prompt = boundary["frame_prompt"]
            end_refs = self.retrieval.images(next_context)
            temporal_candidates = self.retrieval.index(segment, records, ledger)
            if temporal_candidates:
                selected = self.store.operation(
                    key + "/temporal_history",
                    {"context": context, "candidates": temporal_candidates},
                    lambda: self.backend.select_temporal_history(
                        context, temporal_candidates
                    ),
                )
                historical = next(
                    (
                        r
                        for r in records
                        if r["segment"]["id"] == selected["segment_id"]
                    ),
                    None,
                )
                if (
                    historical
                    and historical["segment"]["id"] != context["previous_segment_id"]
                ):
                    extracted = self.store.operation(
                        key + "/historical_shots",
                        {
                            "video": historical["video"],
                            "max_shots": self.policy.max_history_shots,
                        },
                        lambda: extract_shot_ends(
                            historical["video"]["path"],
                            self.store.directory
                            / "historical_shots"
                            / key.replace("/", "-"),
                            max_shots=self.policy.max_history_shots,
                        ),
                    )
                    for item in extracted["candidates"]:
                        verify_media(item["media"])
                    picked = self.store.operation(
                        key + "/historical_boundary",
                        {
                            "context": context,
                            "source": historical,
                            "shots": extracted,
                        },
                        lambda: self.backend.select_historical_boundary(
                            context, historical, extracted
                        ),
                    )
                    historical_seed = next(
                        c["media"]["path"]
                        for c in extracted["candidates"]
                        if c["id"] == picked["shot_id"]
                    )
        end_context = copy.deepcopy(context)
        end_context.update(frame_role="end", next_retrieved_context=next_context)
        end_context["decision"]["frame_prompt"] = end_prompt
        return self.generation.frame(
            segment,
            end_context,
            key + "/planned_end",
            historical_seed,
            [frame["media"]["path"]] + end_refs,
            False,
            check_cancel,
        )

    def _commit(self, key, index, segment, context, frame, end, video, select=True):
        bounds = self.evaluation.boundaries(key + "/selected_bounds", video["media"])
        r = {
            "index": index,
            "segment": asdict(segment),
            "decision": context["decision"],
            "observation": video["observation"],
            "review": video["review"],
            "raw_review": video["raw_review"],
            "video": video["media"],
            "begin": bounds[0],
            "end": bounds[1],
            "condition_frame": frame["media"],
            "condition_end": video.get("end_media"),
            "prompt": video["prompt"],
            "dependencies": list(dict.fromkeys([r["segment"]["id"] for r in context["history"]] +
                next((b.get("depends_on", []) for b in self.store.data.get("plan", {}).get("beats", [])
                      if b["segment_id"] == segment.id), []))),
            "reference_assets": [r["media"] for r in context["references"]],
            "event_assessment": video.get("event_assessment"),
            "completed_goals": [
                g for g in video["review"]["goals"] if g["status"] == "completed"
            ],
            "unresolved_goals": [
                g for g in video["review"]["goals"] if g["status"] != "completed"
            ],
            "state_contract": context["state_contract"],
            "state_observation": video["state_observation"],
            "state_checks": video["state_checks"],
            "mode": video["mode"],
            "requested_mode": context["requested_mode"],
            "candidate_key": video.get("candidate_key", key),
            "accepted": video["accepted"],
            "quality_status": (
                "passed" if video["accepted"] else "best_available_with_issues"
            ),
            "boundary_quality": {
                "begin": frame["accepted"],
                "end": end["accepted"] if end else None,
            },
        }
        if not select:
            return self.store.archive(r)
        self.store.commit(r)
        self.store.data["world_state"] = build_world_state(self.store.data["committed"])
        self.store.save()
        return r
