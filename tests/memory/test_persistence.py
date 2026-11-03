import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from memory import (
    MemoryController,
    MemoryStore,
    Policy,
    Reference,
    Segment,
    QualityBlocked,
)
from memory.contracts.models import validate_observation, validate_review
from memory.contracts.errors import PendingAction as PendingOperation
from fakes import FakeBackend


class PersistenceTests(unittest.TestCase):
    def run_memory(self, backend, segments=None, policy=None):
        segments = segments or self.segments
        refs = []
        for entity in sorted({e for s in segments for e in s.entities}):
            path = self.root / (entity + ".png")
            path.write_bytes(b"anchor")
            refs.append(Reference(entity, str(path), entity, (entity,)))
        policy = policy or Policy(
            global_references=False,
            selection="strict",
            frame_candidates=2,
            video_candidates=2,
        )
        with MemoryStore(self.root / "memory") as store:
            result = MemoryController(store, backend, policy).run(segments, refs)
            return result, json.loads(json.dumps(store.data))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.segments = [
            Segment("s1", "Alice puts down the key", 5, ("Alice",), ("room",)),
            Segment("s2", "Alice walks away", 5, ("Alice",), ("room",)),
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_sequential_observed_state_reaches_next_request_and_resume_is_free(self):
        backend = FakeBackend(continuous=True)
        records, data = self.run_memory(backend)
        videos = [c[1] for c in backend.calls if c[0] == "video"]
        self.assertEqual(videos[1]["begin"], records[0]["end"]["path"])
        self.assertIn("remembered=s1", videos[1]["prompt"])
        self.assertEqual(records[1]["dependencies"], ["s1"])
        before = len(backend.calls)
        self.run_memory(backend)
        self.assertEqual(len(backend.calls), before)
        self.assertNotEqual(records[0]["observation"], asdict(self.segments[0]))

    def test_best_accepted_candidate_not_last_candidate(self):
        records, _ = self.run_memory(FakeBackend((8, 4)), self.segments[:1])
        self.assertTrue(records[0]["video"]["path"].endswith("video-0.mp4"))

    def test_unmet_event_never_becomes_fact_even_with_high_scores(self):
        with self.assertRaises(QualityBlocked):
            self.run_memory(FakeBackend(unmet=True))
        with MemoryStore(self.root / "memory") as persisted:
            state = persisted.data.copy()
        self.assertEqual(state["committed"], [])

    def test_failed_budget_cannot_be_reset_by_restarting(self):
        backend = FakeBackend((2,))
        for _ in range(2):
            with self.assertRaises(QualityBlocked):
                self.run_memory(backend)
        self.assertEqual(backend.video_count, 2)

    def test_interrupted_submission_is_not_repeated(self):
        class Broken(FakeBackend):
            def render_video(self, *args):
                self.video_count += 1
                raise TimeoutError("uncertain submission")

        backend = Broken()
        with self.assertRaises(TimeoutError):
            self.run_memory(backend)
        with self.assertRaises(PendingOperation):
            self.run_memory(backend)
        self.assertEqual(backend.video_count, 1)

    def test_plan_and_media_changes_invalidate_resume(self):
        records, _ = self.run_memory(FakeBackend())
        with self.assertRaises(ValueError):
            self.run_memory(FakeBackend(), [Segment("different", "different", 5)])
        Path(records[0]["video"]["path"]).write_text("tampered")
        with self.assertRaises(RuntimeError):
            self.run_memory(FakeBackend())

    def test_stale_writer_cannot_overwrite_new_state(self):
        from memory.assets.store import ConcurrentSelection
        with MemoryStore(self.root / "memory") as first, MemoryStore(self.root / "memory") as second:
            first.data['marker']='new'
            first.save()
            with self.assertRaises(ConcurrentSelection):second.save()

    def test_invalid_scores_and_out_of_range_evidence_fail_closed(self):
        backend = FakeBackend()
        observation = backend.observe("video", "", self.segments[0])
        observation["events"][0]["end"] = 10
        with self.assertRaises(ValueError):
            validate_observation(observation, 5)
        review = backend.review("frame", "", {}, {})
        review["scores"]["entity_consistency"] = float("nan")
        with self.assertRaises(ValueError):
            validate_review(review, "frame", [])
