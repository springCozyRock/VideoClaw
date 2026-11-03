import copy
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from memory.assets.files import media
from memory.contracts.errors import PendingAction as PendingOperation
from memory.harness.optimization.semantic import (
    ExperienceRepository,
    CachedEmbeddings,
    retrieve,
)


class SemanticTests(unittest.TestCase):
    def test_importer_rejects_experience_that_differs_from_original_candidate_receipts(
        self,
    ):
        importer = runpy.run_path(
            str(
                Path(__file__).resolve().parents[2]
                / "scripts/import_aard_experiences.py"
            )
        )["import_run"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            (run / "memory").mkdir(parents=True)
            (run / "status.json").write_text(json.dumps({"status": "COMPLETED"}))
            a = root / "a.png"
            b = root / "b.png"
            a.write_bytes(b"a")
            b.write_bytes(b"b")
            before = {
                "prompt": "actual before",
                "media": media(a),
                "review": {"scores": {"a": 3}, "hard_failures": []},
            }
            after = {
                "prompt": "actual after",
                "media": media(b),
                "review": {"scores": {"a": 4}, "hard_failures": []},
            }
            exp = {
                "id": "segment/0/begin/1",
                "kind": "frame",
                "label": "pos",
                "original_prompt": before["prompt"],
                "refined_prompt": after["prompt"],
                "before": before["review"],
                "after": after["review"],
            }
            state = {
                "fingerprint": "real-run",
                "inputs": {"segments": [{"id": "story-a"}], "implementation": "v3"},
                "candidates": {"segment/0/begin/0": before, exp["id"]: after},
                "prompt_experiences": [exp],
            }
            checkpoint = run / "memory/memory.json"
            checkpoint.write_text(json.dumps(state))
            self.assertEqual(len(importer(run, root / "repo")), 1)
            exp["refined_prompt"] = "fabricated success"
            checkpoint.write_text(json.dumps(state))
            with self.assertRaisesRegex(ValueError, "differs"):
                importer(run, root / "repo2")

    def test_dense_retrieval_can_rank_without_lexical_overlap(self):
        cases = [
            {
                "id": "semantic",
                "kind": "frame",
                "label": "pos",
                "original_prompt": "remove obsolete garment",
                "before": {"scores": {"a": 3}},
            },
            {
                "id": "lexical",
                "kind": "frame",
                "label": "pos",
                "original_prompt": "脱掉围裙但画天空",
                "before": {"scores": {"a": 3}},
            },
        ]
        result = retrieve(
            cases,
            "frame",
            "脱掉围裙",
            {"scores": {"a": 3}},
            lambda texts: [[1, 0], [0.99, 0.01], [0, 1]],
            top_k=1,
        )
        self.assertEqual(result["pos"][0]["id"], "semantic")

    def test_embedding_receipts_replay_and_unknown_outcomes_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def transport(payload):
                calls.append(payload)
                return {
                    "data": [
                        {"index": i, "embedding": [1, 0]}
                        for i in range(len(payload["input"]))
                    ]
                }

            encoder = CachedEmbeddings(Path(tmp) / "ok", transport, dimensions=2)
            self.assertEqual(encoder(["a"]), encoder(["a"]))
            self.assertEqual(len(calls), 1)

            def failure(payload):
                raise TimeoutError("unknown delivery")

            broken = CachedEmbeddings(Path(tmp) / "unknown", failure, dimensions=2)
            with self.assertRaises(TimeoutError):
                broken(["a"])
            with self.assertRaises(PendingOperation):
                broken(["a"])

    def test_seed_requires_real_media_strict_labels_and_excludes_same_story(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "before.png"
            q = root / "after.png"
            p.write_bytes(b"actual before")
            q.write_bytes(b"actual after")
            case = {
                "id": "real",
                "kind": "frame",
                "label": "pos",
                "original_prompt": "before",
                "refined_prompt": "after",
                "before": {"scores": {"a": 3, "b": 4}},
                "after": {"scores": {"a": 4, "b": 5}, "hard_failures": []},
                "source": {
                    "story_fingerprint": "story-a",
                    "run_fingerprint": "run-a",
                    "before_media": media(p),
                    "after_media": media(q),
                },
            }
            repo = ExperienceRepository(root / "repo")
            repo.add(case)
            self.assertEqual(repo.snapshot("story-a"), [])
            self.assertEqual(len(repo.snapshot("story-b")), 1)
            invalid = copy.deepcopy(case)
            invalid["after"]["scores"]["b"] = 3
            with self.assertRaises(ValueError):
                repo.add(invalid)
            q.write_bytes(b"tampered")
            with self.assertRaises(RuntimeError):
                repo.snapshot("story-b")
