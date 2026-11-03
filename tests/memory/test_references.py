import copy
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict
from memory import MemoryStore, Segment, Reference
from memory.assets.files import media
from memory.world.references.graph import validate_plan, components, initialize
from memory import MemoryController, Policy
from fakes import FakeBackend


class GlobalReferenceTests(unittest.TestCase):
    def node(self, name, deps=(), action="generate"):
        return dict(
            id=name,
            depends_on=list(deps),
            action=action,
            description=name,
            prompt=name,
            reason="story anchor",
            entities=[],
            locations=[],
        )

    def test_cycle_unknown_dependency_and_changed_character_anchor_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            validate_plan({"nodes": [self.node("a", ["b"]), self.node("b", ["a"])]}, [])
        with self.assertRaisesRegex(ValueError, "Unknown"):
            validate_plan({"nodes": [self.node("a", ["absent"])]}, [])
        source = {"id": "a", "entities": ["Alice"]}
        with self.assertRaisesRegex(ValueError, "unchanged"):
            validate_plan({"nodes": [self.node("a")]}, [source])

    def test_dependencies_generate_in_order_and_resume_without_repaying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "official.png"
            path.write_bytes(b"identity")
            source = dict(
                asdict(Reference("alice", str(path), "Alice", ("Alice",))),
                media=media(path),
            )
            nodes = [
                self.node("room", ["alice"]),
                self.node("alice", action="reuse"),
                self.node("object", ["room"]),
            ]

            class Backend(FakeBackend):
                def plan_global_references(self, request):
                    return {"nodes": nodes}

            backend = Backend()
            with MemoryStore(root / "memory") as store:
                result = initialize(
                    store, backend, [Segment("s", "enter room", 5)], [source], 8
                )
                self.assertEqual([r["id"] for r in result], ["alice", "room", "object"])
                self.assertEqual(result[0]["media"], source["media"])
                self.assertEqual(
                    len(components(store.data["global_reference_graph"])), 1
                )
                calls = copy.deepcopy(backend.calls)
                initialize(store, backend, [Segment("s", "enter room", 5)], [source], 8)
                self.assertEqual(backend.calls, calls)
                graph = store.data["global_reference_graph"]
                self.assertEqual(graph["evidence_type"], "planned_reference_assets")
                self.assertEqual(store.data["committed"], [])

    def test_video_extraction_uses_actual_begin_not_condition_image(self):
        class Backend(FakeBackend):
            def observe_with_begin(self, path, segment, asset, initial):
                self.initial_asset = asset
                self.initial_observation = initial
                return dict(
                    self.observe("video", path, segment),
                    extraction={"method": "test_hierarchical"},
                )

        with tempfile.TemporaryDirectory() as tmp:
            backend = Backend()
            with MemoryStore(tmp) as store:
                records = MemoryController(
                    store, backend, Policy(global_references=False)
                ).run([Segment("s", "enter", 5)])
                record = records[0]
                self.assertNotEqual(
                    backend.initial_asset["path"], record["condition_frame"]["path"]
                )
                self.assertIn("observation_bounds", backend.initial_asset["path"])
                op = store.data["operations"]["segment/0/video/0/observe"]["inputs"]
                self.assertEqual(op["initial_observation"], backend.initial_observation)
                self.assertEqual(
                    record["observation"]["extraction"]["method"], "test_hierarchical"
                )


if __name__ == "__main__":
    unittest.main()
