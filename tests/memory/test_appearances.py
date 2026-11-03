import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from memory import (
    MemoryController,
    MemoryStore,
    Policy,
    Segment,
    Reference,
    QualityBlocked,
)
from memory.assets.files import media, digest
from memory.world.state import evaluate
from memory.world.references.character_states import (
    validate_state_plan,
    binding_for,
    state_contract,
    merge_environment_plan,
    compile_state_changes,
)
from fakes import AppearanceBackend, fact, contract, fixture, offline_backend


class PlanTests(unittest.TestCase):
    def test_explicit_removal_stays_removed_in_next_segment(self):
        segments, plan, sources = fixture()
        p = validate_state_plan(plan, [asdict(s) for s in segments], sources)
        contract = state_contract(
            binding_for(p, "s1"), {"daily": "state:daily", "battle": "state:battle"}
        )
        apron = [c for c in contract["conditions"] if c["attribute"] == "wearing_apron"]
        self.assertEqual([c["expected"] for c in apron], [False, False])
        self.assertEqual({c["phase"] for c in apron}, {"begin", "end"})
        self.assertEqual(
            p["evidence_type"], "planned_appearance_requirements_not_observations"
        )

    def test_old_costume_cannot_spontaneously_return(self):
        segments, plan, sources = fixture()
        b = plan["timeline"][1]["bindings"][0]
        b.update(begin_state="daily", end_state="daily")
        with self.assertRaisesRegex(ValueError, "CURRENT shot"):
            validate_state_plan(plan, [asdict(s) for s in segments], sources)

    def test_transition_cannot_quote_character_biography(self):
        segments, plan, sources = fixture()
        segments[0] = Segment(
            "s0",
            "人物介绍：wears apron; remove apron\n分镜列表：\nstands still",
            5,
            ("Penguin",),
        )
        with self.assertRaisesRegex(ValueError, "CURRENT shot"):
            validate_state_plan(plan, [asdict(s) for s in segments], sources)

    def test_new_costume_must_explicitly_define_old_garment_absence(self):
        segments, plan, sources = fixture()
        plan["characters"][0]["states"][1]["attributes"] = {"wearing_armor": True}
        with self.assertRaisesRegex(ValueError, "same attribute keys"):
            validate_state_plan(plan, [asdict(s) for s in segments], sources)

    def test_foreign_state_and_invented_quotes_are_rejected(self):
        segments, plan, sources = fixture()
        plan["timeline"][0]["bindings"][0]["end_state"] = "nonexistent"
        with self.assertRaisesRegex(ValueError, "identities|nonexistent"):
            validate_state_plan(plan, [asdict(s) for s in segments], sources)
        segments, plan, sources = fixture()
        plan["characters"][0]["states"][1]["source_quotes"][0]["quote"] = "invented"
        with self.assertRaisesRegex(ValueError, "literal"):
            validate_state_plan(plan, [asdict(s) for s in segments], sources)

    def test_all_bad_attribute_placeholders_are_reported_together(self):
        segments, plan, sources = fixture()
        for state in plan["characters"][0]["states"]:
            state["attributes"] = {
                "wearing_ITEM": True,
                "holding_ITEM": False,
                "form": None,
            }
        with self.assertRaises(ValueError) as caught:
            validate_state_plan(plan, [asdict(s) for s in segments], sources)
        self.assertIn("wearing_ITEM", str(caught.exception))
        self.assertIn("holding_ITEM", str(caught.exception))
        self.assertIn("not null", str(caught.exception))

    def test_environment_proposals_cannot_omit_or_replace_original_identity(self):
        source = {
            "id": "original",
            "entities": ["Penguin"],
            "locations": [],
            "description": "original identity",
        }
        plan = merge_environment_plan({"nodes": []}, [source], 4)
        self.assertEqual(plan["nodes"][0]["id"], "original")
        self.assertEqual(plan["nodes"][0]["action"], "reuse")
        for node in (
            {"id": "original", "entities": []},
            {"id": "variant", "entities": ["Penguin"]},
        ):
            with self.assertRaises(ValueError):
                merge_environment_plan({"nodes": [node]}, [source], 4)


class CompilerTests(unittest.TestCase):
    def extraction(self):
        return {
            "characters": [
                {
                    "entity": "Penguin",
                    "anchor_id": "original",
                    "identity_description": "same penguin face",
                    "initial_attributes": {"wearing_apron": True},
                    "source_quotes": [{"segment_id": "s0", "quote": "wears apron"}],
                }
            ],
            "changes": [
                {
                    "segment_id": "s0",
                    "entity": "Penguin",
                    "phase": "end",
                    "attributes": {"wearing_apron": False},
                    "quote": "remove apron",
                }
            ],
        }

    def test_compiler_carries_removed_clothing_forward_without_repeating_event(self):
        segments, _, sources = fixture()
        plan = compile_state_changes(
            self.extraction(), [asdict(s) for s in segments], sources
        )
        first, second = [x["bindings"][0] for x in plan["timeline"]]
        self.assertNotEqual(first["begin_state"], first["end_state"])
        self.assertEqual(first["end_state"], second["begin_state"])
        self.assertEqual(second["begin_state"], second["end_state"])
        self.assertIsNone(second["transition_quote"])
        self.assertFalse(
            plan["states_by_id"][second["end_state"]]["attributes"]["wearing_apron"]
        )

    def test_stable_character_has_one_reusable_appearance(self):
        segments, _, sources = fixture()
        data = self.extraction()
        data["characters"][0]["initial_attributes"] = {}
        data["changes"] = []
        plan = compile_state_changes(data, [asdict(s) for s in segments], sources)
        self.assertEqual(len(plan["characters"][0]["states"]), 1)

    def test_missing_initial_value_and_biography_transition_are_rejected(self):
        segments, _, sources = fixture()
        data = self.extraction()
        data["characters"][0]["initial_attributes"] = {}
        with self.assertRaisesRegex(ValueError, "initial value"):
            compile_state_changes(data, [asdict(s) for s in segments], sources)
        data = self.extraction()
        segments[0] = Segment(
            "s0", "wears apron; remove apron\n分镜列表：\nstands still", 5, ("Penguin",)
        )
        with self.assertRaisesRegex(ValueError, "CURRENT shot"):
            compile_state_changes(data, [asdict(s) for s in segments], sources)

    def test_explicit_return_reuses_design_but_does_not_erase_transition(self):
        segments, _, sources = fixture()
        segments[1] = Segment("s1", "put apron back on", 5, ("Penguin",))
        data = self.extraction()
        data["changes"].append(
            {
                "segment_id": "s1",
                "entity": "Penguin",
                "phase": "end",
                "attributes": {"wearing_apron": True},
                "quote": "put apron back on",
            }
        )
        plan = compile_state_changes(data, [asdict(s) for s in segments], sources)
        first, last = [x["bindings"][0] for x in plan["timeline"]]
        self.assertEqual(first["begin_state"], last["end_state"])
        self.assertEqual(len(plan["characters"][0]["states"]), 2)
        self.assertEqual(last["transition_quote"], "put apron back on")


class ControllerTests(unittest.TestCase):
    def test_references_are_prepared_once_and_bound_to_the_correct_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "original.png"
            anchor.write_bytes(b"original apron reference")
            backend = AppearanceBackend(interpolate=True, continuous=False)
            with MemoryStore(root / "run") as store:
                ctl = MemoryController(
                    store, backend, Policy(global_references=False, mapo=False)
                )
                records = ctl.run(
                    fixture()[0],
                    [
                        Reference(
                            "original", str(anchor), "penguin in apron", ("Penguin",)
                        )
                    ],
                )
                registry = store.data["appearance_references"]
                battle = registry["battle"]["media"]["path"]
                begin = store.data["operations"]["segment/0/begin/0/render"]["inputs"][
                    "references"
                ]
                end = store.data["operations"]["segment/0/planned_end/0/render"][
                    "inputs"
                ]["references"]
                self.assertEqual(begin[0], str(anchor.resolve()))
                self.assertNotIn(battle, begin)
                self.assertEqual(end[0], battle)
                self.assertIn("transition_required", records[0]["prompt"])
                self.assertTrue(store.data["appearance_registry_ready"])
                self.assertEqual(
                    records[1]["state_contract"]["conditions"][0]["expected"], False
                )
                count = len(backend.calls)
                ctl.run(
                    fixture()[0],
                    [
                        Reference(
                            "original", str(anchor), "penguin in apron", ("Penguin",)
                        )
                    ],
                )
                self.assertEqual(count, len(backend.calls))

    def test_unverified_state_reference_blocks_video_generation(self):
        class Bad(AppearanceBackend):
            def inspect_reference_state(self, state, asset, anchor, segment):
                return {
                    "checks": {
                        "critical_passed": False,
                        "conditions": [
                            {
                                "status": "failed",
                                "condition": {"attribute": "wearing_apron"},
                                "observed": {"value": True},
                            }
                        ],
                    }
                }

        from memory.contracts.errors import QualityBlocked

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "original.png"
            anchor.write_bytes(b"original")
            backend = Bad()
            with MemoryStore(root / "run") as store:
                with self.assertRaises(QualityBlocked):
                    MemoryController(
                        store, backend, Policy(global_references=False)
                    ).run(
                        fixture()[0],
                        [Reference("original", str(anchor), "penguin", ("Penguin",))],
                    )
                self.assertEqual(backend.video_count, 0)
                self.assertEqual(len(store.data["appearance_candidates"]), 3)

    def test_failed_reference_style_regenerates_without_using_failed_image(self):
        class StyleFailure(AppearanceBackend):
            def __init__(self):
                super().__init__()
                self.battle_checks = 0

            def inspect_reference_state(self, state, asset, anchor, segment):
                if state["id"] == "battle":
                    self.battle_checks += 1
                    if self.battle_checks == 1:
                        return {
                            "checks": {
                                "critical_passed": False,
                                "conditions": [
                                    {
                                        "status": "failed",
                                        "condition": {
                                            "attribute": "style_matches_anchor"
                                        },
                                        "observed": {"value": False},
                                    }
                                ],
                            }
                        }
                return super().inspect_reference_state(state, asset, anchor, segment)

        from memory.assets.files import digest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "original.png"
            anchor.write_bytes(b"original")
            with MemoryStore(root / "run") as store:
                ctl = MemoryController(
                    store, StyleFailure(), Policy(global_references=False, mapo=False)
                )
                ctl.run(
                    fixture()[0],
                    [Reference("original", str(anchor), "penguin", ("Penguin",))],
                )
                key = "appearance/reference/" + digest("battle")[:16]
                failed = store.data["operations"][key + "/0/render"]["result"]["path"]
                retry = store.data["operations"][key + "/1/render"]["inputs"]
                self.assertEqual(retry["reference_action"], "regenerate")
                self.assertNotIn(failed, retry["references"])
                self.assertEqual(retry["references"][0], str(anchor.resolve()))

    def test_new_shape_derives_from_verified_single_state_parent_but_is_checked_against_original(
        self,
    ):
        class NormalizeFirst(AppearanceBackend):
            def __init__(self):
                super().__init__()
                self.first = True
                self.inspected_anchors = []

            def inspect_reference_state(self, state, asset, anchor, segment):
                self.inspected_anchors.append(anchor["media"]["path"])
                if state["id"] == "daily" and self.first:
                    self.first = False
                    return {
                        "checks": {
                            "critical_passed": False,
                            "conditions": [
                                {
                                    "status": "failed",
                                    "condition": {"attribute": "style_matches_anchor"},
                                    "observed": {"value": False},
                                }
                            ],
                        }
                    }
                return super().inspect_reference_state(state, asset, anchor, segment)

        from memory.assets.files import digest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "mixed_sheet.png"
            anchor.write_bytes(b"mixed outfits")
            backend = NormalizeFirst()
            with MemoryStore(root / "run") as store:
                MemoryController(
                    store, backend, Policy(global_references=False, mapo=False)
                ).run(
                    fixture()[0],
                    [Reference("original", str(anchor), "penguin", ("Penguin",))],
                )
                clean = store.data["appearance_references"]["daily"]["media"]["path"]
                request = store.data["operations"][
                    "appearance/reference/" + digest("battle")[:16] + "/0/render"
                ]["inputs"]
                self.assertEqual(request["references"], [clean])
                self.assertNotEqual(clean, str(anchor.resolve()))
                self.assertEqual(
                    set(backend.inspected_anchors), {str(anchor.resolve())}
                )


class BackendTests(unittest.TestCase):
    def test_single_frame_missing_motion_is_explicitly_unobservable_not_invented(self):
        b = offline_backend()
        value = {
            "entities": [
                {
                    "id": "Penguin",
                    "kind": "character",
                    "identity": "penguin",
                    "state": "wearing apron",
                    "evidence": [{"start": 0, "end": 0, "detail": "visible"}],
                }
            ],
            "spatial_relations": [],
            "camera": "front",
            "events": [],
        }
        b.transport.structured = lambda instruction, data, validator, **kw: validator(
            value
        )
        result = b.observe("frame", "/actual.png", fixture()[0][0])
        self.assertEqual(
            result["entities"][0]["motion"],
            "Motion is not observable from a single still frame.",
        )


class VisibilityTests(unittest.TestCase):
    def test_visible_absence_is_observed_false_while_occlusion_remains_unknown(self):
        from memory.world.state import facts_from_visibility

        slot = {"entity": "Penguin", "attribute": "wearing_glasses", "phase": "end"}
        base = dict(
            slot,
            entity_visible=True,
            attribute_observable=True,
            value=False,
            reason="Bare face is visible",
            evidence=[{"start": 0, "end": 0, "detail": "Bare face"}],
        )
        self.assertEqual(
            facts_from_visibility({"facts": [base]}, [slot], 0)["facts"][0]["status"],
            "observed",
        )
        self.assertEqual(
            facts_from_visibility(
                {"facts": [dict(base, attribute_observable=False, value=None)]},
                [slot],
                0,
            )["facts"][0]["status"],
            "unknown",
        )
        self.assertEqual(
            facts_from_visibility(
                {
                    "facts": [
                        dict(
                            base,
                            entity_visible=False,
                            attribute_observable=False,
                            value=None,
                        )
                    ]
                },
                [slot],
                0,
            )["facts"][0]["status"],
            "not_visible",
        )

    def test_invisible_character_cannot_establish_absence_or_boolean_presence(self):
        from memory.world.state import facts_from_visibility

        slot = {"entity": "Penguin", "attribute": "wearing_glasses", "phase": "end"}
        base = dict(
            slot,
            entity_visible=False,
            attribute_observable=True,
            value=False,
            reason="offscreen",
            evidence=[],
        )
        with self.assertRaises(ValueError):
            facts_from_visibility({"facts": [base]}, [slot], 0)
        with self.assertRaises(ValueError):
            facts_from_visibility(
                {"facts": [dict(base, entity_visible=True, value="false")]}, [slot], 0
            )


class ScaleTests(unittest.TestCase):
    def test_scale_word_alias_does_not_relax_actual_size_or_other_attributes(self):
        from memory.world.state import equal_state_value

        self.assertTrue(equal_state_value("scale", "gigantic", "giant"))
        self.assertFalse(equal_state_value("scale", "large", "giant"))
        self.assertFalse(equal_state_value("scale", "normal", "small"))
        self.assertFalse(equal_state_value("form", "gigantic", "giant"))
        self.assertFalse(equal_state_value("wearing_glasses", "false", False))


class HITSDecisionTests(unittest.TestCase):
    def test_regenerate_does_not_require_unused_edit_prompt_but_edit_does(self):
        b = offline_backend()
        result = {
            "mode": "regenerate",
            "reason": "fundamental style mismatch",
            "single_issue": "style",
            "edit_prompt": "",
        }
        b.transport.structured = lambda instruction, data, validator, **kw: validator(
            result
        )
        self.assertEqual(b.choose_frame_action({}, {})["mode"], "regenerate")
        result["mode"] = "edit"
        with self.assertRaises(ValueError):
            b.choose_frame_action({}, {})


class VisibilityTimelineTests(unittest.TestCase):
    def fact(self):
        return {
            "entity": "A",
            "attribute": "identity_matches_anchor",
            "phase": "throughout",
            "entity_visible": True,
            "attribute_observable": True,
            "value": True,
            "reason": "Matches when visible; then the shot cuts to B",
            "evidence": [{"start": 0, "end": 1, "detail": "A is visible and matches"}],
            "visibility_intervals": [
                {"start": 0, "end": 1, "visibility": "visible"},
                {"start": 1, "end": 5, "visibility": "offscreen"},
            ],
        }

    def parse(self, value):
        from memory.world.state import facts_from_visibility

        return facts_from_visibility(
            {"facts": [value]},
            [{k: value[k] for k in ("entity", "attribute", "phase")}],
            5,
        )

    def test_legitimate_closeup_does_not_require_offscreen_identity_evidence(self):
        self.assertEqual(self.parse(self.fact())["facts"][0]["status"], "observed")

    def test_uncertain_visibility_and_missing_visible_evidence_cannot_pass(self):
        f = self.fact()
        f["visibility_intervals"][1]["visibility"] = "uncertain"
        self.assertEqual(self.parse(f)["facts"][0]["status"], "unknown")
        f = self.fact()
        f["visibility_intervals"] = [{"start": 0, "end": 5, "visibility": "visible"}]
        result = self.parse(f)["facts"][0]
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["value"])
        self.assertTrue(result["reported_observation"]["value"])

    def test_gaps_and_fabricated_offscreen_evidence_are_rejected(self):
        f = self.fact()
        f["visibility_intervals"][1]["start"] = 2
        with self.assertRaises(ValueError):
            self.parse(f)
        f = self.fact()
        f["evidence"][0]["end"] = 5
        self.assertEqual(self.parse(f)["facts"][0]["status"], "unknown")


class ReferenceReuseTests(unittest.TestCase):
    def test_reuse_requires_same_state_anchor_media_and_current_predicates(self):
        import json
        from memory.world.references.character_states import reuse_verified_appearances

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "ref.png"
            image.write_bytes(b"original")
            asset = media(image)
            segments, plan, sources = fixture()
            sources[0]["media"] = asset
            plan = validate_state_plan(plan, [asdict(s) for s in segments], sources)
            state = plan["states_by_id"]["daily"]
            ref = {"id": "state:daily", "media": asset}
            facts = [
                dict(
                    fact(value=True, phase="end", duration=0),
                    entity="Penguin",
                    attribute=a,
                )
                for a in (
                    "wearing_apron",
                    "identity_matches_anchor",
                    "style_matches_anchor",
                )
            ]
            checkpoint = {
                "inputs": {"references": sources},
                "appearance_plan": plan,
                "appearance_references": {"daily": ref},
                "appearance_candidates": {
                    "0": {
                        "state_id": "daily",
                        "media": asset,
                        "inspection": {"observation": {"facts": facts}},
                    }
                },
            }
            path = root / "memory.json"
            path.write_text(json.dumps(checkpoint))
            receipt = media(path)
            self.assertIn(
                "daily",
                reuse_verified_appearances(receipt, plan, sources)["references"],
            )
            changed = copy.deepcopy(plan)
            changed["states_by_id"]["daily"]["attributes"]["wearing_apron"] = False
            self.assertEqual(
                reuse_verified_appearances(receipt, changed, sources)["references"], {}
            )
            checkpoint["appearance_candidates"]["0"]["inspection"]["observation"][
                "facts"
            ][0]["value"] = False
            path.write_text(json.dumps(checkpoint))
            receipt = media(path)
            self.assertEqual(
                reuse_verified_appearances(receipt, plan, sources)["references"], {}
            )
            image.write_bytes(b"changed media")
            with self.assertRaises(RuntimeError):
                reuse_verified_appearances(receipt, plan, sources)


class IncompleteEvidenceTests(unittest.TestCase):
    def test_incomplete_proof_is_quality_unknown_not_processing_failure_or_pass(self):
        from memory.world.state import conservative_facts, evaluate

        slot = {
            "entity": "Rabbit",
            "attribute": "identity_matches_anchor",
            "phase": "throughout",
        }
        original = dict(
            slot,
            status="observed",
            value=True,
            reason="claims identity",
            evidence=[{"start": 0, "end": 3, "detail": "observed 0..3"}],
            visibility_intervals=[
                {"start": 0, "end": 4, "visibility": "visible"},
                {"start": 4, "end": 6, "visibility": "offscreen"},
            ],
        )
        observed = conservative_facts({"facts": [original]}, [slot], 6)
        self.assertEqual(observed["facts"][0]["status"], "unknown")
        self.assertTrue(original["value"])
        checked = evaluate(
            {
                "conditions": [
                    dict(slot, expected=True, critical=True, visibility="when_visible")
                ]
            },
            observed,
            [slot],
        )
        self.assertFalse(checked["critical_passed"])
        self.assertEqual(checked["conditions"][0]["status"], "uncertain")
        self.assertEqual(conservative_facts(observed, [slot], 6), observed)

    def test_gap_between_evidence_intervals_is_not_silently_covered(self):
        from memory.world.state import conservative_facts

        slot = {
            "entity": "Rabbit",
            "attribute": "identity_matches_anchor",
            "phase": "throughout",
        }
        row = dict(
            slot,
            status="observed",
            value=True,
            reason="claims entire clip",
            evidence=[
                {"start": 0, "end": 2, "detail": "first"},
                {"start": 4, "end": 6, "detail": "last"},
            ],
            visibility_intervals=[{"start": 0, "end": 6, "visibility": "visible"}],
        )
        self.assertEqual(
            conservative_facts({"facts": [row]}, [slot], 6)["facts"][0]["status"],
            "unknown",
        )
