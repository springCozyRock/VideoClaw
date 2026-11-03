"""Deterministic providers and real adapter components with mocked transport."""

import copy
from pathlib import Path
from unittest.mock import Mock
from memory import Segment
from memory.contracts.models import FRAME_METRICS, VIDEO_METRICS
from memory.world.references.character_states import validate_state_plan, state_contract
from memory.adapters.videoclaw import VideoClawBackend
from memory.adapters.videoclaw.transport import StructuredTransport
from memory.adapters.videoclaw.planning import Planning
from memory.adapters.videoclaw.inspection import Inspection
from memory.adapters.videoclaw.media import MediaIO


def contract(phase="end"):
    return {
        "conditions": [
            {
                "id": "apron_removed",
                "entity": "Penguin",
                "attribute": "wearing_apron",
                "expected": False,
                "phase": phase,
                "critical": True,
                "goal": "remove apron",
                "source": {"type": "script", "quote": "remove apron"},
            }
        ]
    }


def fact(status="observed", value=True, phase="end", duration=5):
    return {
        "entity": "Penguin",
        "attribute": "wearing_apron",
        "phase": phase,
        "status": status,
        "value": value,
        "reason": (
            "Visible apron remains" if value else "Torso fully visible without apron"
        ),
        "evidence": (
            [{"start": duration, "end": duration, "detail": "Actual decoded boundary"}]
            if status == "observed"
            else []
        ),
    }


class FakeBackend:
    def __init__(
        self,
        video_scores=(9,),
        continuous=False,
        unmet=False,
        interpolate=False,
        bad_video=False,
        bad_first_frame=False,
        action="edit",
    ):
        self.calls = []
        self.video_scores = video_scores
        self.continuous = continuous
        self.unmet = unmet
        self.video_count = 0
        self.interpolate = interpolate
        self.ends = []
        self.bad_video = bad_video
        self.bad_first_frame = bad_first_frame
        self.action = action

    def identity(self):
        return {"capabilities": {"last_frame": True}, "fake": True}

    def prepare(self, context):
        self.calls.append(("prepare", context))
        result = {
            "continuous": self.continuous and bool(context["history"]),
            "continuity_reason": "test fixture",
            "goals": ["place key on table"],
            "allowed_changes": ["key changes possession"],
            "frame_prompt": "key is held",
            "video_prompt": "place key on table; remembered="
            + ",".join(r["segment"]["id"] for r in context["history"]),
        }
        result.update(
            goals=["remove apron"],
            no_new_environment=not self.interpolate,
            next_contiguous=True,
            end_frame_prompt="final key state, preserve layout",
        )
        return result

    def render_frame(self, segment, prompt, references, target):
        self.calls.append(("frame", list(references)))
        target.write_text("fake image " + segment.id)
        return str(target)

    def render_video(self, segment, prompt, begin, target):
        self.calls.append(
            ("video", {"prompt": prompt, "begin": begin, "segment": segment.id})
        )
        self.video_count += 1
        target.write_text("fake video " + str(self.video_count))
        return str(target)

    def observe(self, kind, path, segment):
        self.calls.append(("observe", kind))
        return {
            "entities": [
                {
                    "id": "Alice",
                    "kind": "character",
                    "identity": "dark hair",
                    "state": "holding key" if kind == "frame" else "key on table",
                    "motion": "hand moves",
                    "evidence": [
                        {"start": 0, "end": 0, "detail": "visible hand and key"}
                    ],
                }
            ],
            "spatial_relations": [],
            "camera": "static",
            "events": (
                []
                if kind == "frame"
                else [{"start": 1, "end": 2, "detail": "key is put down"}]
            ),
        }

    def review(self, kind, path, observation, request):
        score = (
            9
            if kind == "frame"
            else self.video_scores[
                min(self.video_count - 1, len(self.video_scores) - 1)
            ]
        )
        result = {
            "scores": {
                m: score for m in (FRAME_METRICS if kind == "frame" else VIDEO_METRICS)
            },
            "issues": [] if score >= 7 else ["identity drift"],
            "hard_failures": [],
            "goals": (
                []
                if kind == "frame"
                else [
                    {
                        "goal": "place key on table",
                        "status": "unmet" if self.unmet else "completed",
                        "evidence": "visible at 2s",
                    }
                ]
            ),
        }
        result["goals"] = (
            []
            if kind == "frame"
            else [
                {
                    "goal": g,
                    "status": "unmet" if self.unmet else "completed",
                    "evidence": "model claims success",
                }
                for g in request["context"]["decision"]["goals"]
            ]
        )
        return result

    def refine(self, kind, candidate, request):
        return candidate["prompt"] + "; repair drift"

    def boundaries(self, video, directory):
        directory.mkdir(parents=True, exist_ok=True)
        paths = [directory / "begin.png", directory / "end.png"]
        for path in paths:
            path.write_text("fake decoded " + path.name + " from " + video)
        return [str(p) for p in paths]

    def select_context(self, query):
        return {
            "segment_ids": [p["id"] for p in query["previous"]][-query["top_k"] :],
            "reference_ids": [],
        }

    def plan_global_references(self, request):
        return {
            "nodes": [
                dict(
                    dict(
                        s, entities=list(s["entities"]), locations=list(s["locations"])
                    ),
                    action="reuse",
                    depends_on=[],
                    prompt="reuse anchor",
                    reason="existing",
                )
                for s in request["sources"]
            ]
            + [
                {
                    "id": "test/global",
                    "description": "test global",
                    "entities": [],
                    "locations": [],
                    "action": "generate",
                    "depends_on": [],
                    "prompt": "test global",
                    "reason": "test",
                }
            ]
        }

    def observe_with_begin(self, path, segment, asset, initial):
        return self.observe("video", path, segment)

    def render_with_end(self, segment, prompt, begin, end, target):
        self.ends.append(end)
        return self.render_video(segment, prompt, begin, target)

    def end_edit_prompt(self, *args):
        return "repair identity, keep actual final layout"

    def refine_with_memory(self, kind, candidate, request, cases):
        return self.refine(kind, candidate, request)

    def prepare_state_contract(self, context, decision):
        return contract()

    def inspect_state(
        self, kind, path, requested, segment, references, actual_bounds=None
    ):
        self.calls.append(("inspect_state", copy.deepcopy(requested)))
        bad = (
            self.bad_video
            and (
                kind == "video"
                or ("observation_bounds" in path and path.endswith("end.png"))
            )
        ) or (kind == "frame" and self.bad_first_frame and path.endswith("-0.png"))
        return {
            "facts": [
                dict(
                    fact(
                        value=(
                            True
                            if s["attribute"]
                            in ("identity_matches_anchor", "style_matches_anchor")
                            else bad
                        ),
                        phase=s["phase"],
                        duration=0 if kind == "frame" else segment.duration,
                    ),
                    entity=s["entity"],
                    attribute=s["attribute"],
                )
                for s in requested
            ]
        }

    def choose_frame_action(self, candidate, request):
        return {
            "mode": self.action,
            "single_issue": "apron remains",
            "reason": "targeted fixture",
            "edit_prompt": "remove apron only",
        }

    def prepare_next_boundary(self, context, next_context):
        self.calls.append(("next_boundary", copy.deepcopy(next_context)))
        return {"frame_prompt": "opening of " + next_context["segment"]["id"]}

    def select_temporal_history(self, context, candidates):
        return {"segment_id": None, "reason": "No historical resumption"}

    def embed_texts(self, texts):
        return [[1, 0] for _ in texts]

    def review_global_reference(self, node, asset, anchors):
        return {
            "style_consistent": True,
            "identity_consistent": True,
            "unwanted_entities": False,
            "issues": [],
        }

    def plan_character_states(self, request):
        characters = []
        for entity in sorted({e for s in request["segments"] for e in s["entities"]}):
            anchor = next(a for a in request["sources"] if entity in a["entities"])
            segment = next(s for s in request["segments"] if entity in s["entities"])
            characters.append(
                {
                    "entity": entity,
                    "anchor_id": anchor["id"],
                    "identity_description": "stable " + entity,
                    "states": [
                        {
                            "id": entity,
                            "description": "stable design",
                            "attributes": {},
                            "prompt": "stable design",
                            "source_quotes": [
                                {
                                    "segment_id": segment["id"],
                                    "quote": segment["context"],
                                }
                            ],
                        }
                    ],
                }
            )
        return {
            "characters": characters,
            "timeline": [
                {
                    "segment_id": s["id"],
                    "bindings": [
                        {"entity": e, "begin_state": e, "end_state": e}
                        for e in s["entities"]
                    ],
                }
                for s in request["segments"]
            ],
        }

    def inspect_reference_state(self, state, asset, anchor, segment):
        return {"observation": {"facts": []}, "checks": {"critical_passed": True}}


def fixture():
    segments = [
        Segment("s0", "wears apron; remove apron", 5, ("Penguin",)),
        Segment("s1", "fight without transforming again", 5, ("Penguin",)),
    ]
    plan = {
        "characters": [
            {
                "entity": "Penguin",
                "anchor_id": "original",
                "identity_description": "same penguin face and body",
                "states": [
                    {
                        "id": "daily",
                        "description": "daily apron",
                        "attributes": {"wearing_apron": True},
                        "prompt": "penguin in apron",
                        "source_quotes": [{"segment_id": "s0", "quote": "wears apron"}],
                    },
                    {
                        "id": "battle",
                        "description": "battle without apron",
                        "attributes": {"wearing_apron": False},
                        "prompt": "same penguin without apron",
                        "source_quotes": [
                            {"segment_id": "s0", "quote": "remove apron"}
                        ],
                    },
                ],
            }
        ],
        "timeline": [
            {
                "segment_id": "s0",
                "bindings": [
                    {
                        "entity": "Penguin",
                        "begin_state": "daily",
                        "end_state": "battle",
                        "transition_quote": "remove apron",
                    }
                ],
            },
            {
                "segment_id": "s1",
                "bindings": [
                    {
                        "entity": "Penguin",
                        "begin_state": "battle",
                        "end_state": "battle",
                        "transition_quote": None,
                    }
                ],
            },
        ],
    }
    sources = [{"id": "original", "entities": ["Penguin"]}]
    return segments, plan, sources


class AppearanceBackend(FakeBackend):
    def plan_character_states(self, request):
        return validate_state_plan(
            fixture()[1], request["segments"], request["sources"]
        )

    def inspect_reference_state(self, state, asset, anchor, segment):
        self.calls.append(("reference_inspection", state["id"]))
        return {"observation": {"facts": []}, "checks": {"critical_passed": True}}

    def prepare_state_contract(self, context, decision):
        return state_contract(
            context["appearance_binding"], context["state_reference_ids"]
        )

    def inspect_state(
        self, kind, path, requested, segment, references, actual_bounds=None
    ):
        result = []
        for slot in requested:
            v = (
                segment.id == "s0" and slot["phase"] == "begin"
                if slot["attribute"] == "wearing_apron"
                else True
            )
            f = dict(
                fact(
                    value=v,
                    phase=slot["phase"],
                    duration=0 if kind == "frame" else segment.duration,
                ),
                **slot
            )
            if slot["phase"] == "throughout" and kind == "video":
                f["evidence"][0]["start"] = 0
            result.append(f)
        return {"facts": result}


def offline_backend():
    backend = VideoClawBackend.__new__(VideoClawBackend)
    backend.agent = Mock()
    backend.judge = Mock()
    backend.transport = StructuredTransport(backend.agent, backend.judge)
    backend.media = MediaIO.__new__(MediaIO)
    backend.planning = Planning(backend.transport)
    backend.inspection = Inspection(backend.transport, backend.media)
    return backend
