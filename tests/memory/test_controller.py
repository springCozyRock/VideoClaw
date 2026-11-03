import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from memory import (
    MemoryController,
    MemoryStore,
    Policy,
    Segment,
    Reference,
    QualityBlocked,
)
from memory.assets.files import media
from fakes import FakeBackend, fact, contract


class ControllerTests(unittest.TestCase):
    def test_video_final_state_is_observed_as_an_independent_actual_frame(self):
        class InspectCalls(FakeBackend):
            def inspect_state(
                self, kind, path, requested, segment, references, actual_bounds=None
            ):
                self.calls.append(
                    (
                        "exact_state_call",
                        {
                            "kind": kind,
                            "path": path,
                            "slots": requested,
                            "bounds": actual_bounds,
                        },
                    )
                )
                return super().inspect_state(
                    kind, path, requested, segment, references, actual_bounds
                )

        with tempfile.TemporaryDirectory() as tmp:
            b = InspectCalls()
            result, state = self.run_case(tmp, b)
            op = state["operations"]["segment/0/video/0/inspect_state/end"]
            self.assertTrue(op["inputs"]["asset"]["path"].endswith("end.png"))
            call = [
                x[1]
                for x in b.calls
                if x[0] == "exact_state_call"
                and x[1]["path"] == op["inputs"]["asset"]["path"]
            ][0]
            self.assertEqual(call["kind"], "frame")
            self.assertIsNone(call["bounds"])
            fact = result[0]["state_observation"]["facts"][0]
            self.assertEqual(fact["boundary_evidence"]["frame_evidence"][0]["start"], 0)
            self.assertEqual(fact["evidence"][0]["end"], 5)

    def run_case(self, root, backend, segments=None, **policy):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        anchor = root / "original.png"
        anchor.write_bytes(b"anchor")
        with MemoryStore(root) as store:
            result = MemoryController(
                store,
                backend,
                Policy(
                    global_references=False,
                    frame_candidates=2,
                    video_candidates=2,
                    **policy
                ),
            ).run(
                segments or [Segment("s0", "remove apron", 5, ("Penguin",), ("room",))],
                [Reference("anchor", str(anchor), "penguin", ("Penguin",))],
            )
            return result, copy.deepcopy(store.data)

    def test_high_scores_cannot_commit_failed_critical_state_or_reset_budget_on_resume(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            b = FakeBackend(bad_video=True, interpolate=True)
            for _ in range(2):
                with self.assertRaises(QualityBlocked):
                    self.run_case(tmp, b)
            with MemoryStore(tmp) as persisted:
                state = persisted.data.copy()
            self.assertEqual(state["committed"], [])
            self.assertEqual(b.video_count, 2)
            candidate = state["candidates"]["segment/0/video/0"]
            self.assertEqual(candidate["raw_review"]["goals"][0]["status"], "completed")
            self.assertEqual(candidate["review"]["goals"][0]["status"], "unmet")

    def test_world_state_is_available_to_next_plan_and_resume_does_not_repeat_calls(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            b = FakeBackend(continuous=True)
            segments = [
                Segment("s0", "remove apron", 5, ("Penguin",), ("room",)),
                Segment("s1", "remove apron", 5, ("Penguin",), ("room",)),
            ]
            result, state = self.run_case(tmp, b, segments)
            next_context = state["operations"]["segment/1/prepare"]["inputs"]
            self.assertIs(
                next_context["world_state"][0]["latest"]["fact"]["value"], False
            )
            self.assertEqual(result[1]["condition_frame"], result[0]["end"])
            count = len(b.calls)
            self.run_case(tmp, b, segments)
            self.assertEqual(len(b.calls), count)

    def test_next_segment_reference_retrieval_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = FakeBackend(interpolate=True)
            segments = [
                Segment("s0", "remove apron", 5, ("Penguin",), ("room",)),
                Segment("s1", "remove apron", 5, ("Penguin",), ("garden",)),
            ]
            _, state = self.run_case(tmp, b, segments)
            request = state["operations"]["segment/0/retrieve_next"]["inputs"]
            self.assertEqual(request["current"]["id"], "s1")
            self.assertEqual(
                state["operations"]["segment/0/next_boundary"]["result"][
                    "frame_prompt"
                ],
                "opening of s1",
            )

    def test_nonadjacent_scene_uses_a_selected_real_historical_shot_end(self):
        class HistoricalBackend(FakeBackend):
            def select_temporal_history(self, context, candidates):
                return {"segment_id": "s0", "reason": "Resume earlier scene"}

            def select_historical_boundary(self, context, source_record, extracted):
                return {
                    "shot_id": "shot-000",
                    "reason": "Earlier scene end fits resumption",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "historical-end.png"
            real.write_bytes(b"actual historical boundary")
            b = HistoricalBackend(interpolate=True)
            segments = [
                Segment("s" + str(i), "remove apron", 5, ("Penguin",), ("room",))
                for i in range(4)
            ]
            with patch(
                "memory.runtime.controller.extract_shot_ends",
                return_value={"candidates": [{"id": "shot-000", "media": media(real)}]},
            ) as detector:
                result, state = self.run_case(root / "run", b, segments)
                detector.assert_called_once()
                self.assertEqual(result[2]["condition_end"], media(real))
                self.assertIn("segment/2/historical_boundary", state["operations"])

    def test_reference_style_failure_blocks_before_any_video_generation(self):
        class BadStyle(FakeBackend):
            def review_global_reference(self, node, asset, anchors):
                return {
                    "style_consistent": False,
                    "identity_consistent": True,
                    "unwanted_entities": False,
                    "issues": ["photographic instead of watercolor"],
                }

        with tempfile.TemporaryDirectory() as tmp:
            b = BadStyle()
            with MemoryStore(tmp) as store:
                with self.assertRaisesRegex(QualityBlocked, "Global reference"):
                    MemoryController(store, b, Policy(reference_candidates=2)).run(
                        [Segment("s0", "remove apron", 5)]
                    )
                self.assertEqual(b.video_count, 0)
                self.assertEqual(len([x for x in b.calls if x[0] == "frame"]), 2)

    def test_edit_uses_failed_frame_but_regenerate_discards_it(self):
        for action in ["edit", "regenerate"]:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                b = FakeBackend(bad_first_frame=True, action=action)
                with MemoryStore(tmp) as store:
                    store.data["prompt_experiences"] = []
                    store.data["seed_experiences"] = []
                    ctl = MemoryController(
                        store, b, Policy(global_references=False, mapo=False)
                    )
                    segment = Segment("s0", "remove apron", 5, ("Penguin",))
                    context = {
                        "state_contract": contract("begin"),
                        "frame_role": "begin",
                        "references": [],
                        "decision": {
                            "frame_prompt": "remove apron",
                            "goals": ["remove apron"],
                        },
                    }
                    result = ctl.generation.frame(
                        segment, context, "begin", "", [], False, None
                    )
                    first = str(Path(tmp).resolve() / "media/begin-0.png")
                    calls = [x[1] for x in b.calls if x[0] == "frame"]
                    self.assertEqual(first in calls[1], action == "edit")
                    self.assertTrue(result["accepted"])
