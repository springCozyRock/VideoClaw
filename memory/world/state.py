"""Evidence-backed state predicates; intentions never update observed world state."""

import copy
import math
import re
import unicodedata
from memory.assets.files import digest

PHASES = ("begin", "end", "throughout")
STATE_SCHEMA = (
    "identity_matches_anchor",
    "style_matches_anchor",
    "form",
    "scale",
    "sleep_state",
)


def durable_contract(value):
    """This gate covers identity and mutable entity state; the main rubric covers action/VFX."""
    raw = value.get("conditions")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 40:
        raise ValueError("State contract needs 1..40 proposed conditions")
    result = copy.deepcopy(value)
    kept = []
    outside = []
    for condition in raw:
        attribute = condition.get("attribute", "")
        if attribute in STATE_SCHEMA or (
            isinstance(attribute, str)
            and re.fullmatch(r"(wearing|holding|carrying)_[a-z][a-z0-9_]*", attribute)
        ):
            kept.append(copy.deepcopy(condition))
        else:
            outside.append(copy.deepcopy(condition))
    result.update(
        conditions=kept,
        out_of_scope_conditions=outside,
        schema_scope="Identity/style, garments, held/carried props, form, scale and sleep state. Motion/VFX/scene actions remain in the primary video rubric.",
    )
    return result


def scalar(value):
    return isinstance(value, (str, bool, int, float)) and (
        not isinstance(value, float) or math.isfinite(value)
    )


def slot_key(item):
    return (item["entity"], item["attribute"], item["phase"])


def validate_contract(value, entities, goals, source_text, reference_ids=()):
    conditions = value.get("conditions")
    if not isinstance(conditions, list) or not conditions or len(conditions) > 40:
        raise ValueError("State contract needs 1..40 explicit conditions")
    seen, ids = set(), set()
    for c in conditions:
        if not isinstance(c.get("id"), str) or not c["id"] or c["id"] in ids:
            raise ValueError("Unique condition ids required")
        ids.add(c["id"])
        if c.get("entity") not in entities or c.get("phase") not in PHASES:
            raise ValueError("Unknown stable entity or phase")
        if not isinstance(c.get("attribute"), str) or not re.fullmatch(
            "[a-z][a-z0-9_]{0,79}", c["attribute"]
        ):
            raise ValueError("Attributes must use stable snake_case predicate names")
        if slot_key(c) in seen:
            raise ValueError("Conflicting or duplicate state condition")
        seen.add(slot_key(c))
        if not scalar(c.get("expected")) or type(c.get("critical")) is not bool:
            raise ValueError("Explicit expected scalar and critical boolean required")
        if c.get("visibility", "required") not in ("required", "when_visible"):
            raise ValueError("Unknown visibility policy")
        if c.get("persistence", "segment") not in ("segment", "until_changed"):
            raise ValueError("Unknown state persistence")
        if c.get("goal") is not None and c["goal"] not in goals:
            raise ValueError("Condition references an unknown goal")
        provenance = c.get("source", {})
        if provenance.get("type") == "script":
            quote = provenance.get("quote")
            if (
                not isinstance(quote, str)
                or not quote.strip()
                or quote not in source_text
            ):
                raise ValueError(
                    "State intention requires a literal current-source quote for "
                    + c["id"]
                    + ": "
                    + repr(quote)
                    + "; no ellipses or paraphrases"
                )
        elif provenance.get("type") == "reference":
            if provenance.get("reference_id") not in reference_ids:
                raise ValueError("Unknown identity/style anchor")
            if (
                c["attribute"]
                not in ("identity_matches_anchor", "style_matches_anchor")
                or c["expected"] is not True
            ):
                raise ValueError(
                    "Reference contracts constrain identity/style, not mutable costume"
                )
        else:
            raise ValueError("State condition requires source provenance")
    for c in conditions:
        if c["phase"] == "throughout":
            for other in conditions:
                if (other["entity"], other["attribute"]) == (
                    c["entity"],
                    c["attribute"],
                ) and not equal_value(other["expected"], c["expected"]):
                    raise ValueError(
                        "A throughout condition contradicts a boundary condition: "
                        + c["id"]
                        + " versus "
                        + other["id"]
                    )
    return value


def slots(contract, kind, role="begin"):
    phases = (
        PHASES
        if kind == "video"
        else (("begin", "throughout") if role == "begin" else ("end", "throughout"))
    )
    # Expected values, script text and intended outcomes are deliberately omitted.
    return [
        dict(entity=c["entity"], attribute=c["attribute"], phase=c["phase"])
        for c in contract["conditions"]
        if c["phase"] in phases
    ]


class InsufficientTemporalEvidence(ValueError):
    """Well-formed observation with insufficient visual support; a quality outcome."""

    pass


def validate_visibility_timeline(fact, duration):
    intervals = fact.get("visibility_intervals")
    if not isinstance(intervals, list) or not intervals:
        raise ValueError(
            "Video throughout facts need a visibility timeline covering the clip"
        )
    previous = 0
    visible = []
    uncertain = []
    for item in intervals:
        start, end = item.get("start"), item.get("end")
        visibility = item.get("visibility")
        if (
            any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in (start, end)
            )
            or not 0 <= start < end <= duration
        ):
            raise ValueError("Visibility intervals need valid clip times")
        if abs(start - previous) > 1e-3:
            raise ValueError(
                "Visibility intervals must cover the clip without gaps or overlaps"
            )
        if visibility not in ("visible", "offscreen", "uncertain"):
            raise ValueError("Unknown visibility interval label")
        if visibility == "visible":
            visible.append(item)
        if visibility == "uncertain":
            uncertain.append(item)
        previous = end
    if abs(previous - duration) > 1e-3:
        raise ValueError("Visibility timeline must end at the actual clip duration")
    if fact["status"] == "not_visible" and (visible or uncertain):
        raise ValueError("Only a fully offscreen entity is not_visible throughout")
    if fact["status"] == "observed":
        if not visible:
            raise ValueError(
                "Observed throughout value needs at least one visible window"
            )
        if uncertain:
            raise InsufficientTemporalEvidence(
                "Visibility is uncertain in part of the clip"
            )
        evidence = fact["evidence"]
        tolerance = 0.26  # one 4-fps sampling interval
        for window in visible:
            matching = [
                e
                for e in evidence
                if e["end"] >= window["start"] and e["start"] <= window["end"]
            ]
            cursor = window["start"]
            for e in sorted(matching, key=lambda e: e["start"]):
                if e["start"] > cursor + tolerance:
                    raise InsufficientTemporalEvidence(
                        "A visible interval has an unsupported evidence gap"
                    )
                cursor = max(cursor, e["end"])
            if cursor < window["end"] - tolerance:
                raise InsufficientTemporalEvidence(
                    "Throughout evidence does not cover the complete visible interval"
                )
        for e in evidence:
            if not any(
                w["start"] - tolerance <= e["start"] <= e["end"] <= w["end"] + tolerance
                for w in visible
            ):
                raise InsufficientTemporalEvidence(
                    "Reported state evidence crosses an explicitly offscreen interval"
                )
    return intervals


def validate_facts(value, requested, duration):
    facts = value.get("facts")
    if not isinstance(facts, list) or len(facts) != len(requested):
        raise ValueError(
            "Every requested state slot must be observed or explicitly unknown"
        )
    allowed = {slot_key(s) for s in requested}
    seen = set()
    for f in facts:
        key = slot_key(f)
        if key not in allowed or key in seen:
            raise ValueError("Unknown or duplicate observed slot")
        seen.add(key)
        if f.get("status") not in ("observed", "unknown", "not_visible"):
            raise ValueError("State status must be observed or unknown")
        if not isinstance(f.get("reason"), str) or not f["reason"].strip():
            raise ValueError(
                "State observation needs evidence explanation or uncertainty"
            )
        evidence = f.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError("Evidence must be a list")
        if f["status"] in ("unknown", "not_visible"):
            if f.get("value") is not None:
                raise ValueError("Unknown is not an observed absent/false value")
        elif not scalar(f.get("value")) or not evidence:
            raise ValueError(
                "Observed facts require scalar values and temporal evidence"
            )
        for e in evidence:
            if any(
                type(e.get(k)) not in (int, float) or not math.isfinite(e[k])
                for k in ("start", "end")
            ):
                raise ValueError("Numeric finite evidence times required")
            if (
                not 0 <= e["start"] <= e["end"] <= duration
                or not isinstance(e.get("detail"), str)
                or not e["detail"].strip()
            ):
                raise ValueError("Invalid state evidence")
        if f["status"] == "observed" and duration:
            if f["phase"] == "end" and not any(
                e["end"] >= duration - min(1, duration / 4) for e in evidence
            ):
                raise ValueError("Initial evidence cannot establish final state")
            if f["phase"] == "begin" and not any(
                e["start"] <= min(0.5, duration / 4) for e in evidence
            ):
                raise ValueError("Late evidence cannot establish initial state")
            if (
                f["phase"] == "throughout"
                and "visibility_intervals" not in f
                and (
                    min(e["start"] for e in evidence) > min(0.5, duration / 4)
                    or max(e["end"] for e in evidence) < duration - min(1, duration / 4)
                )
            ):
                raise ValueError("Throughout evidence must cover both boundaries")
        if duration and f["phase"] == "throughout" and "visibility_intervals" in f:
            validate_visibility_timeline(f, duration)
    for f in facts:
        if f["phase"] == "throughout" and f["status"] == "observed":
            for other in facts:
                if (
                    (other["entity"], other["attribute"])
                    == (f["entity"], f["attribute"])
                    and other["status"] == "observed"
                    and not equal_value(other["value"], f["value"])
                ):
                    raise ValueError("Throughout fact contradicts an observed boundary")
    return value


def conservative_facts(value, requested, duration):
    """Insufficient proof becomes explicit unknown, never a pass or a transport error."""
    result = copy.deepcopy(value)
    for f in result.get("facts", []):
        slot = {k: f[k] for k in ("entity", "attribute", "phase")}
        try:
            validate_facts({"facts": [f]}, [slot], duration)
        except InsufficientTemporalEvidence as exc:
            reported = copy.deepcopy(f)
            f.update(
                status="unknown",
                value=None,
                attribute_observable=False,
                reason="Insufficient temporal evidence: "
                + str(exc)
                + ". Original report: "
                + f.get("reason", ""),
                quality_issue=str(exc),
                reported_observation=reported,
            )
    return validate_facts(result, requested, duration)


def equal_value(actual, expected):
    if type(actual) is bool or type(expected) is bool:
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, str) and isinstance(expected, str):
        return (
            unicodedata.normalize("NFKC", actual).strip().casefold()
            == unicodedata.normalize("NFKC", expected).strip().casefold()
        )
    return (
        type(actual) in (int, float)
        and type(expected) in (int, float)
        and actual == expected
    )


def equal_state_value(attribute, actual, expected):
    # Narrow lexical equivalence, not a relaxed size threshold: "large" is
    # deliberately NOT an alias for "giant". Raw evidence remains unchanged.
    if attribute == "scale" and isinstance(actual, str) and isinstance(expected, str):
        aliases = {"gigantic": "giant"}

        def canonical(v):
            v = unicodedata.normalize("NFKC", v).strip().casefold()
            return aliases.get(v, v)

        return canonical(actual) == canonical(expected)
    return equal_value(actual, expected)


def evaluate(contract, observation, requested):
    by_key = {slot_key(f): f for f in observation["facts"]}
    wanted = {slot_key(s) for s in requested}
    results = []
    for condition in contract["conditions"]:
        if slot_key(condition) not in wanted:
            continue
        fact = by_key[slot_key(condition)]
        if (
            fact["status"] == "not_visible"
            and condition.get("visibility") == "when_visible"
        ):
            status = "not_applicable"
        else:
            status = (
                "uncertain"
                if fact["status"] != "observed"
                else (
                    "passed"
                    if equal_state_value(
                        condition["attribute"], fact["value"], condition["expected"]
                    )
                    else "failed"
                )
            )
        results.append(
            {
                "condition": copy.deepcopy(condition),
                "observed": copy.deepcopy(fact),
                "status": status,
            }
        )
    return {
        "conditions": results,
        "critical_passed": all(
            r["status"] in ("passed", "not_applicable")
            for r in results
            if r["condition"]["critical"]
        ),
    }


def constrain_review(review, checks):
    result = copy.deepcopy(review)
    for check in checks["conditions"]:
        if check["status"] in ("passed", "not_applicable"):
            continue
        c = check["condition"]
        f = check["observed"]
        message = f"State {c['entity']}.{c['attribute']} at {c['phase']}: expected {c['expected']!r}, observed {f['value']!r} ({check['status']}); {f['reason']}"
        if message not in result["issues"]:
            result["issues"].append(message)
        if c["critical"] and message not in result["hard_failures"]:
            result["hard_failures"].append(message)
        for goal in result["goals"]:
            if goal["goal"] == c["goal"] and goal["status"] == "completed":
                goal.update(
                    status="unmet" if check["status"] == "failed" else "uncertain",
                    evidence=message,
                )
    # Model rubric numbers are kept intact, even when contradicted by predicate checks.
    return result


def build_world_state(records):
    ledger = {}
    for record in records:
        # End evidence wins over a coarser interval summary regardless of model list order.
        for fact in sorted(
            record.get("state_observation", {}).get("facts", []),
            key=lambda f: f["phase"] == "end",
        ):
            if fact["phase"] not in ("end", "throughout"):
                continue
            key = fact["entity"] + "/" + fact["attribute"]
            version = {
                "segment_id": record["segment"]["id"],
                "index": record["index"],
                "video": record["video"],
                "fact": copy.deepcopy(fact),
                "quality_passed": record["accepted"],
                "state_checks_passed": record.get("state_checks", {}).get(
                    "critical_passed", False
                ),
            }
            row = ledger.setdefault(
                key,
                {
                    "entity": fact["entity"],
                    "attribute": fact["attribute"],
                    "versions": [],
                },
            )
            row["versions"].append(version)
            row["latest"] = version
            if fact["status"] == "observed":
                row["last_observed"] = version
    return ledger


def compact_world(ledger):
    return [
        {k: copy.deepcopy(v) for k, v in row.items() if k != "versions"}
        for row in ledger.values()
    ]


def persistent_requirements(records):
    """Previous intentions with provenance, NEVER a substitute for observations."""
    rows = {}
    for record in records:
        for c in record.get("state_contract", {}).get("conditions", []):
            if (
                c["phase"] in ("end", "throughout")
                and c.get("persistence") == "until_changed"
            ):
                rows[(c["entity"], c["attribute"])] = {
                    "condition": copy.deepcopy(c),
                    "segment_id": record["segment"]["id"],
                }
    return list(rows.values())


def inherit_requirements(contract, previous, entities):
    """Persist appearance changes across reappearances; explicit audited changes take precedence."""
    result = copy.deepcopy(contract)
    conditions = result["conditions"]
    for row in previous:
        old = row["condition"]
        if old["entity"] not in entities:
            continue
        present = [
            c
            for c in conditions
            if (c["entity"], c["attribute"]) == (old["entity"], old["attribute"])
        ]
        for phase in ("begin", "end"):
            if any(c["phase"] in (phase, "throughout") for c in present):
                continue
            inherited = copy.deepcopy(old)
            inherited.update(
                id="carry_" + digest([row["segment_id"], old["id"], phase])[:16],
                phase=phase,
                goal=None,
                visibility="when_visible",
                persistence="until_changed",
                source={
                    "type": "memory",
                    "segment_id": row["segment_id"],
                    "condition_id": old["id"],
                    "original_source": old["source"],
                },
            )
            conditions.append(inherited)
    return result


def state_contract_id(contract):
    return digest(contract)


def facts_from_visibility(value, requested, duration):
    """Keep entity visibility separate from visible absence of an attribute."""
    raw = value.get("facts")
    if not isinstance(raw, list):
        raise ValueError("facts must be a list")
    facts = []
    for row in raw:
        present = row.get("entity_visible")
        observable = row.get("attribute_observable")
        if present is not None and type(present) is not bool:
            raise ValueError("entity_visible is true/false/null")
        if type(observable) is not bool:
            raise ValueError("attribute_observable is boolean")
        v = row.get("value")
        if observable:
            if present is not True or not scalar(v):
                raise ValueError(
                    "An observable property needs a visible entity and definite value"
                )
            attr = row.get("attribute", "")
            if (
                attr.startswith(("wearing_", "holding_", "carrying_"))
                or attr in ("identity_matches_anchor", "style_matches_anchor")
            ) and type(v) is not bool:
                raise ValueError(
                    "Observable presence/identity predicates need boolean true or false; visible absence is false"
                )
            status = "observed"
        else:
            if v is not None:
                raise ValueError(
                    "Unassessable attribute needs null value, not a guessed true/false"
                )
            status = "not_visible" if present is False else "unknown"
        if (
            duration
            and row.get("phase") == "throughout"
            and not isinstance(row.get("visibility_intervals"), list)
        ):
            raise ValueError(
                "Provide visibility_intervals for the whole clip: visible/offscreen/uncertain. Evidence covers visible windows only; do not stretch it over an intentional close-up of someone else."
            )
        facts.append(dict(row, status=status))
    return conservative_facts({"facts": facts}, requested, duration)
