import copy
import unittest
from memory.contracts.models import VIDEO_METRICS
from memory.world.state import (
    validate_contract,
    validate_facts,
    evaluate,
    constrain_review,
    build_world_state,
    slots,
    persistent_requirements,
    inherit_requirements,
    durable_contract,
)
from fakes import fact, contract


class StateTests(unittest.TestCase):
    def test_durable_state_gate_does_not_turn_transient_effects_into_persistent_identity(
        self,
    ):
        raw = contract()
        effect = copy.deepcopy(raw["conditions"][0])
        effect.update(
            id="flash",
            attribute="emitting_blue_electricity",
            expected=True,
            phase="throughout",
        )
        raw["conditions"].append(effect)
        scoped = durable_contract(raw)
        self.assertEqual(len(scoped["conditions"]), 1)
        self.assertEqual(scoped["out_of_scope_conditions"], [effect])
        self.assertEqual(len(raw["conditions"]), 2)

    def test_removed_clothing_persists_across_absence_without_becoming_observed_fact(
        self,
    ):
        c = contract()
        c["conditions"][0]["persistence"] = "until_changed"
        rows = persistent_requirements(
            [{"segment": {"id": "transformation"}, "state_contract": c}]
        )
        empty = {"conditions": []}
        self.assertEqual(inherit_requirements(empty, rows, ["Cat"]), empty)
        returned = inherit_requirements(empty, rows, ["Penguin"])
        self.assertEqual({x["phase"] for x in returned["conditions"]}, {"begin", "end"})
        self.assertTrue(all(x["expected"] is False for x in returned["conditions"]))
        self.assertTrue(
            all(
                x["source"]["segment_id"] == "transformation"
                for x in returned["conditions"]
            )
        )
        self.assertEqual(build_world_state([{"state_contract": returned}]), {})
        changed = contract()
        changed["conditions"][0]["expected"] = True
        merged = inherit_requirements(changed, rows, ["Penguin"])
        self.assertEqual(
            {x["phase"]: x["expected"] for x in merged["conditions"]},
            {"begin": False, "end": True},
        )

    def test_interval_claim_requires_boundary_coverage_and_cannot_contradict_end(self):
        whole = fact(value=True, phase="throughout")
        requested = [{k: whole[k] for k in ("entity", "attribute", "phase")}]
        with self.assertRaisesRegex(ValueError, "both boundaries"):
            validate_facts({"facts": [whole]}, requested, 5)
        whole["evidence"][0]["start"] = 0
        ending = fact(value=False)
        requested.append({k: ending[k] for k in ("entity", "attribute", "phase")})
        with self.assertRaisesRegex(ValueError, "contradicts"):
            validate_facts({"facts": [whole, ending]}, requested, 5)

    def test_false_goal_completion_is_overridden_without_changing_model_scores(self):
        c = contract()
        requested = slots(c, "video")
        observed = {"facts": [fact()]}
        checks = evaluate(c, validate_facts(observed, requested, 5), requested)
        original = {
            "scores": {k: 10 for k in VIDEO_METRICS},
            "issues": [],
            "hard_failures": [],
            "goals": [
                {
                    "goal": "remove apron",
                    "status": "completed",
                    "evidence": "incorrect model conclusion",
                }
            ],
        }
        result = constrain_review(original, checks)
        self.assertEqual(result["scores"], original["scores"])
        self.assertEqual(result["goals"][0]["status"], "unmet")
        self.assertTrue(result["hard_failures"])
        self.assertEqual(original["goals"][0]["status"], "completed")

    def test_unknown_does_not_mean_absent_and_begin_evidence_does_not_establish_end(
        self,
    ):
        c = contract()
        requested = slots(c, "video")
        observed = {"facts": [fact("unknown", None)]}
        checks = evaluate(c, validate_facts(observed, requested, 5), requested)
        self.assertFalse(checks["critical_passed"])
        self.assertEqual(checks["conditions"][0]["status"], "uncertain")
        bad = {"facts": [fact(duration=0)]}
        with self.assertRaisesRegex(ValueError, "Initial evidence"):
            validate_facts(bad, requested, 5)
        observed["facts"][0]["value"] = False
        with self.assertRaisesRegex(ValueError, "Unknown"):
            validate_facts(observed, requested, 5)

    def test_contract_requires_source_and_observer_never_receives_expected_values(self):
        c = contract()
        validate_contract(c, ["Penguin"], ["remove apron"], "Please remove apron now")
        self.assertEqual(
            slots(c, "video"),
            [{"entity": "Penguin", "attribute": "wearing_apron", "phase": "end"}],
        )
        c["conditions"][0]["source"]["quote"] = "invented change"
        with self.assertRaisesRegex(ValueError, "literal"):
            validate_contract(c, ["Penguin"], ["remove apron"], "remove apron")

    def test_world_ledger_keeps_observed_error_and_uncertainty_not_planned_desired_state(
        self,
    ):
        records = [
            {
                "index": 0,
                "segment": {"id": "s0"},
                "video": {"path": "actual"},
                "accepted": False,
                "state_checks": {"critical_passed": False},
                "state_contract": contract(),
                "state_observation": {"facts": [fact(value=True)]},
            },
            {
                "index": 1,
                "segment": {"id": "s1"},
                "video": {"path": "actual2"},
                "accepted": False,
                "state_checks": {"critical_passed": False},
                "state_observation": {"facts": [fact("unknown", None)]},
            },
        ]
        row = build_world_state(records)["Penguin/wearing_apron"]
        self.assertIs(row["last_observed"]["fact"]["value"], True)
        self.assertIsNone(row["latest"]["fact"]["value"])
        self.assertEqual(len(row["versions"]), 2)
