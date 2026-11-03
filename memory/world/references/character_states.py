"""Story-planned appearance states and their segment bindings; never observed facts."""

import copy
import re
from memory.world.state import scalar, equal_value
from memory.assets.files import digest


def shot_text(segment):
    from prompting.language import shot_source
    return shot_source(segment["context"])


def validate_state_plan(plan, segments, sources):
    by_segment = {s["id"]: s for s in segments}
    anchors = {r["id"]: r for r in sources if r["entities"]}
    wanted = {e for s in segments for e in s["entities"]}
    characters = plan.get("characters")
    timeline = plan.get("timeline")
    if (
        not isinstance(characters, list)
        or {c.get("entity") for c in characters} != wanted
        or len(characters) != len(wanted)
    ):
        raise ValueError("Plan every scripted character exactly once")
    # Report all malformed attributes together so one bounded schema retry can
    # correct the complete response, rather than discovering errors one by one.
    invalid = []
    for character in characters:
        for state in (
            character.get("states", [])
            if isinstance(character.get("states"), list)
            else []
        ):
            attrs = state.get("attributes")
            if not isinstance(attrs, dict):
                continue
            for attribute, value in attrs.items():
                allowed = attribute in ("form", "scale", "sleep_state") or re.fullmatch(
                    r"(wearing|holding|carrying)_[a-z][a-z0-9_]*", attribute
                )
                if not allowed or attribute.endswith(("_item", "_object")):
                    invalid.append(
                        str(state.get("id"))
                        + ": unsupported/placeholder key "
                        + attribute
                    )
                elif not scalar(value):
                    invalid.append(
                        str(state.get("id"))
                        + ": "
                        + attribute
                        + " must be a definite scalar, not null"
                    )
                elif (
                    attribute.startswith(("wearing_", "holding_", "carrying_"))
                    and type(value) is not bool
                ):
                    invalid.append(
                        str(state.get("id")) + ": " + attribute + " must be boolean"
                    )
    if invalid:
        raise ValueError(
            "Invalid appearance attributes: "
            + "; ".join(invalid)
            + ". Use lowercase predicates naming actual scripted items (e.g. wearing_red_hat), never ITEM or unspecified item/object. "
            "Omit inapplicable properties; attributes={} is valid for a stable design. Do not invent new items to fill the schema."
        )
    states = {}
    for character in characters:
        entity = character["entity"]
        anchor = anchors.get(character.get("anchor_id"))
        if not anchor or entity not in anchor["entities"]:
            raise ValueError("Character must bind to its own supplied identity anchor")
        if (
            not isinstance(character.get("identity_description"), str)
            or not character["identity_description"].strip()
        ):
            raise ValueError("Stable identity description required")
        variants = character.get("states")
        if not isinstance(variants, list) or not 1 <= len(variants) <= 6:
            raise ValueError("Use 1..6 necessary appearance states per character")
        keys = None
        for state in variants:
            sid = state.get("id")
            if not isinstance(sid, str) or not sid or sid in states:
                raise ValueError("Unique nonempty state ids required")
            for k in ("description", "prompt"):
                if not isinstance(state.get(k), str) or not state[k].strip():
                    raise ValueError("State needs " + k)
            attrs = state.get("attributes")
            if not isinstance(attrs, dict) or len(attrs) > 12:
                raise ValueError("State attributes must be a small explicit map")
            if keys is None:
                keys = set(attrs)
            if set(attrs) != keys:
                raise ValueError(
                    "All states of one entity must specify the same attribute keys, including absent items"
                )
            for attribute, value in attrs.items():
                if not (
                    attribute in ("form", "scale", "sleep_state")
                    or re.fullmatch(
                        r"(wearing|holding|carrying)_[a-z][a-z0-9_]*", attribute
                    )
                ):
                    raise ValueError(
                        "Unsupported durable state attribute: " + attribute
                    )
                if not scalar(value):
                    raise ValueError("State attributes need definite scalar values")
                if (
                    attribute.startswith(("wearing_", "holding_", "carrying_"))
                    and type(value) is not bool
                ):
                    raise ValueError("Garment/prop predicates must be booleans")
            quotes = state.get("source_quotes")
            if not isinstance(quotes, list) or not quotes:
                raise ValueError("Every appearance design needs source provenance")
            for item in quotes:
                source = by_segment.get(item.get("segment_id"))
                quote = item.get("quote")
                if (
                    not source
                    or not isinstance(quote, str)
                    or not quote.strip()
                    or quote not in source["context"]
                ):
                    raise ValueError(
                        "Appearance source quote must be a literal segment substring"
                    )
            states[sid] = dict(
                copy.deepcopy(state), entity=entity, anchor_id=character["anchor_id"]
            )
    if not isinstance(timeline, list) or [
        x.get("segment_id") for x in timeline
    ] != list(by_segment):
        raise ValueError("Timeline must cover every segment once in original order")
    previous = {}
    for item in timeline:
        segment = by_segment[item["segment_id"]]
        bindings = item.get("bindings")
        if (
            not isinstance(bindings, list)
            or len(bindings) != len(set(segment["entities"]))
            or {b.get("entity") for b in bindings} != set(segment["entities"])
        ):
            raise ValueError("Bind exactly the characters appearing in each segment")
        for binding in bindings:
            entity = binding["entity"]
            begin = states.get(binding.get("begin_state"))
            end = states.get(binding.get("end_state"))
            if (
                not begin
                or not end
                or begin["entity"] != entity
                or end["entity"] != entity
            ):
                raise ValueError(
                    "State binding crosses identities or references nonexistent state"
                )
            changed = begin["id"] != end["id"] or (
                entity in previous and previous[entity] != begin["id"]
            )
            quote = binding.get("transition_quote")
            if changed and (
                not isinstance(quote, str)
                or not quote.strip()
                or quote not in shot_text(segment)
            ):
                raise ValueError(
                    "State changes/restoration need an explicit CURRENT shot quote: "
                    + entity
                )
            previous[entity] = end["id"]
    return dict(
        copy.deepcopy(plan),
        states_by_id=states,
        evidence_type="planned_appearance_requirements_not_observations",
    )


def binding_for(plan, segment_id):
    item = next(x for x in plan["timeline"] if x["segment_id"] == segment_id)
    return {
        "segment_id": segment_id,
        "bindings": [
            dict(
                copy.deepcopy(b),
                begin=plan["states_by_id"][b["begin_state"]],
                end=plan["states_by_id"][b["end_state"]],
            )
            for b in item["bindings"]
        ],
    }


def state_contract(binding, reference_ids):
    conditions = []
    for b in binding["bindings"]:
        entity = b["entity"]
        before = b["begin"]["attributes"]
        after = b["end"]["attributes"]
        for attribute in before:
            same = equal_value(before[attribute], after[attribute])
            # Check boundaries separately. Clothing can be temporarily hidden or
            # removed during a scripted transition, even if endpoint states match.
            for phase, values, state in [
                ("begin", before, b["begin"]),
                ("end", after, b["end"]),
            ]:
                conditions.append(
                    {
                        "id": digest([entity, attribute, phase])[:16],
                        "entity": entity,
                        "attribute": attribute,
                        "expected": values[attribute],
                        "phase": phase,
                        "critical": True,
                        "visibility": (
                            "required"
                            if phase == "end" and not same
                            else "when_visible"
                        ),
                        "persistence": "until_changed",
                        "goal": None,
                        "source": {
                            "type": "planned_state",
                            "state_id": state["id"],
                            "source_quotes": state["source_quotes"],
                        },
                    }
                )
        for attribute in ("identity_matches_anchor", "style_matches_anchor"):
            ref = reference_ids[b["begin_state"]]
            conditions.append(
                {
                    "id": digest([entity, attribute])[:16],
                    "entity": entity,
                    "attribute": attribute,
                    "expected": True,
                    "phase": "throughout",
                    "critical": True,
                    "visibility": "when_visible",
                    "persistence": "segment",
                    "goal": None,
                    "source": {"type": "reference", "reference_id": ref},
                }
            )
    return {
        "conditions": conditions,
        "origin": "Validated global appearance plan and explicit segment state bindings",
    }


def merge_environment_plan(value, sources, max_dependencies):
    """Keep supplied anchors in code; the model proposes environment/object edits only."""
    from memory.world.references.graph import validate_plan

    nodes = value.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("Reference proposals require nodes list; [] is valid")
    original = {r["id"]: r for r in sources}
    combined = {
        r["id"]: {
            "id": r["id"],
            "action": "reuse",
            "description": r["description"],
            "entities": list(r["entities"]),
            "locations": list(r["locations"]),
            "depends_on": [],
            "prompt": "Reuse the supplied original reference unchanged.",
            "reason": "Preserve supplied source anchor.",
        }
        for r in sources
    }
    seen = set()
    for node in nodes:
        name = node.get("id")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("Unique reference proposal ids required")
        seen.add(name)
        if name in original and original[name]["entities"]:
            raise ValueError(
                "Do not propose modifications to character anchors; they are retained automatically"
            )
        if node.get("entities"):
            raise ValueError(
                "Character appearance assets belong exclusively to the state registry"
            )
        combined[name] = node
    return validate_plan(
        {"nodes": list(combined.values()), "original_anchors_retained_in_code": True},
        sources,
        max_dependencies=max_dependencies,
    )


def compile_state_changes(value, segments, sources):
    """Compile initial appearances plus explicit changes into a complete state timeline.

    Models identify source facts; code carries unchanged values forward and reuses
    identical designs. No model-generated full snapshots or hand-written case plans.
    """
    import json

    definitions = value.get("characters")
    changes = value.get("changes")
    wanted = {e for s in segments for e in s["entities"]}
    if (
        not isinstance(definitions, list)
        or len(definitions) != len(wanted)
        or {c.get("entity") for c in definitions} != wanted
    ):
        raise ValueError("Define every scripted character exactly once. Expected exact names: " + repr(sorted(wanted)) + "; returned definitions: " + repr(definitions))
    if not isinstance(changes, list):
        raise ValueError(
            "changes must be a list; [] is valid when appearance never changes"
        )
    source_by_id = {s["id"]: s for s in segments}
    defs = {c["entity"]: c for c in definitions}
    schema_errors = []
    for c in definitions:
        attrs = c.get("initial_attributes")
        if not isinstance(attrs, dict):
            schema_errors.append(c["entity"] + ": initial_attributes must be a map")
            continue
        maps = [attrs] + [
            change.get("attributes", {})
            for change in changes
            if change.get("entity") == c["entity"]
        ]
        for values in maps:
            if not isinstance(values, dict):
                continue
            for attribute, value in values.items():
                if not (
                    attribute in ("form", "scale", "sleep_state")
                    or re.fullmatch(
                        r"(wearing|holding|carrying)_[a-z][a-z0-9_]*", attribute
                    )
                ):
                    schema_errors.append(
                        c["entity"] + ": unsupported attribute " + attribute
                    )
                elif not scalar(value) or (
                    attribute.startswith(("wearing_", "holding_", "carrying_"))
                    and type(value) is not bool
                ):
                    schema_errors.append(
                        c["entity"] + ": invalid value type for " + attribute
                    )
        missing = sorted(
            {
                k
                for values in maps[1:]
                if isinstance(values, dict)
                for k in values
                if k not in attrs
            }
        )
        if missing:
            schema_errors.append(
                c["entity"]
                + ": changed attributes missing explicit initial values: "
                + ", ".join(missing)
            )
    if schema_errors:
        raise ValueError(
            "Appearance extraction schema errors: "
            + "; ".join(dict.fromkeys(schema_errors))
            + ". Define the initial value of every changed attribute explicitly from source evidence; never infer absent versus unknown. "
            "Use scale for a source-supported size change; describe stable anatomy in identity_description. Do not invent initial values or new story events."
        )
    grouped = {}
    used_slots = set()
    for change in changes:
        segment = source_by_id.get(change.get("segment_id"))
        entity = change.get("entity")
        phase = change.get("phase")
        attrs = change.get("attributes")
        quote = change.get("quote")
        if (
            not segment
            or entity not in segment["entities"]
            or phase not in ("begin", "end")
        ):
            raise ValueError(
                "Every appearance change needs a listed segment, present entity and begin/end phase"
            )
        if not isinstance(attrs, dict) or not attrs:
            raise ValueError("Appearance change needs actual changed attributes")
        if (
            not isinstance(quote, str)
            or not quote.strip()
            or quote not in shot_text(segment)
        ):
            raise ValueError("Appearance change requires an exact CURRENT shot quote")
        initial = defs[entity].get("initial_attributes")
        if not isinstance(initial, dict) or not set(attrs) <= set(initial):
            raise ValueError(
                "Define the initial value of every changed attribute explicitly; never infer absent versus unknown"
            )
        for attribute in attrs:
            slot = (segment["id"], entity, phase, attribute)
            if slot in used_slots:
                raise ValueError("Duplicate appearance change slot")
            used_slots.add(slot)
        grouped.setdefault((segment["id"], entity, phase), []).append(change)
    characters = []
    current = {}
    state_by_signature = {}
    evidence = {}
    for c in definitions:
        entity = c["entity"]
        attrs = c.get("initial_attributes")
        if not isinstance(attrs, dict):
            raise ValueError(
                "initial_attributes must be a map; {} is valid for a stable appearance"
            )
        current[entity] = copy.deepcopy(attrs)
        state_by_signature[entity] = {}
        evidence[entity] = copy.deepcopy(c.get("source_quotes", []))
        characters.append(
            {
                "entity": entity,
                "anchor_id": c.get("anchor_id"),
                "identity_description": c.get("identity_description"),
                "states": [],
            }
        )
    output = {c["entity"]: c for c in characters}

    def register(entity):
        attrs = current[entity]
        signature = digest(attrs)
        if signature in state_by_signature[entity]:
            return state_by_signature[entity][signature]
        sid = "appearance_" + digest([entity, attrs])[:16]
        identity = defs[entity].get("identity_description", "")
        state = {
            "id": sid,
            "description": identity
            + "; required appearance "
            + json.dumps(attrs, ensure_ascii=False),
            "attributes": copy.deepcopy(attrs),
            "prompt": identity
            + ". Create one clear character reference. Required appearance attributes: "
            + json.dumps(attrs, ensure_ascii=False)
            + ". False garments/props must be absent. Preserve stable identity and original art style.",
            "source_quotes": copy.deepcopy(evidence[entity]),
        }
        output[entity]["states"].append(state)
        state_by_signature[entity][signature] = sid
        return sid

    timeline = []
    for segment in segments:
        bindings = []
        for entity in segment["entities"]:
            quotes = []

            def apply(phase):
                for change in grouped.get((segment["id"], entity, phase), []):
                    if all(
                        equal_value(current[entity][k], v)
                        for k, v in change["attributes"].items()
                    ):
                        raise ValueError(
                            "Redundant appearance change: "
                            + entity
                            + " "
                            + segment["id"]
                        )
                    current[entity].update(change["attributes"])
                    quotes.append(change["quote"])
                    evidence[entity].append(
                        {"segment_id": segment["id"], "quote": change["quote"]}
                    )

            apply("begin")
            begin = register(entity)
            apply("end")
            end = register(entity)
            bindings.append(
                {
                    "entity": entity,
                    "begin_state": begin,
                    "end_state": end,
                    "transition_quote": (
                        quotes[0]
                        if len(quotes) == 1
                        else shot_text(segment) if quotes else None
                    ),
                }
            )
        timeline.append({"segment_id": segment["id"], "bindings": bindings})
    return validate_state_plan(
        {
            "characters": characters,
            "timeline": timeline,
            "compiled_from_source_changes": copy.deepcopy(value),
        },
        segments,
        sources,
    )


def reuse_verified_appearances(receipt, plan, original):
    """Adopt only hash-verified assets whose old raw observation passes current predicates."""
    import json
    from pathlib import Path
    from memory.assets.files import verify_media
    from memory.world.state import validate_facts, evaluate

    verify_media(receipt)
    source = json.loads(Path(receipt["path"]).read_text())
    old_states = source.get("appearance_plan", {}).get("states_by_id", {})
    old_anchors = {r["id"]: r for r in source.get("inputs", {}).get("references", [])}
    anchors = {r["id"]: r for r in original}
    refs = {}
    checks = {}
    for sid, ref in source.get("appearance_references", {}).items():
        state = plan["states_by_id"].get(sid)
        if not state or digest(state) != digest(old_states.get(sid)):
            continue
        anchor = anchors.get(state["anchor_id"])
        old_anchor = old_anchors.get(state["anchor_id"])
        if not anchor or not old_anchor or anchor["media"] != old_anchor["media"]:
            continue
        verify_media(anchor["media"])
        verify_media(ref["media"])
        candidates = [
            c
            for c in source.get("appearance_candidates", {}).values()
            if c.get("state_id") == sid and c.get("media") == ref["media"]
        ]
        if not candidates:
            continue
        observation = candidates[-1].get("inspection", {}).get("observation")
        if not observation:
            continue
        requested = [
            {"entity": state["entity"], "attribute": a, "phase": "end"}
            for a in state["attributes"]
        ]
        requested += [
            {"entity": state["entity"], "attribute": a, "phase": "end"}
            for a in ("identity_matches_anchor", "style_matches_anchor")
        ]
        validate_facts(observation, requested, 0)
        conditions = [
            dict(
                slot,
                id=str(i),
                expected=state["attributes"].get(slot["attribute"], True),
                critical=True,
                visibility="required",
                goal=None,
            )
            for i, slot in enumerate(requested)
        ]
        checked = evaluate({"conditions": conditions}, observation, requested)
        if checked["critical_passed"]:
            refs[sid] = copy.deepcopy(ref)
            checks[sid] = checked
    return {"references": refs, "checks": checks, "source_checkpoint": receipt}
