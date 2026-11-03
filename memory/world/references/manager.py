"""Initialize verified references and route planned appearances to each boundary."""

import copy
import json
from dataclasses import asdict
from memory.contracts.errors import QualityBlocked
from memory.contracts.models import Segment, Reference
from memory.assets.files import digest, media, verify_media
from memory.world.references.graph import initialize as initialize_references
from memory.world.references.character_states import binding_for, validate_state_plan, reuse_verified_appearances


class ReferenceMemory:
    def __init__(self, store, backend, policy):
        self.store, self.backend, self.policy = store, backend, policy

    def initialize(self, segments, original, cancel):
        request = {"segments": [asdict(s) for s in segments], "sources": original}
        plan = self.store.operation(
            "appearance/plan",
            request,
            lambda: self.backend.plan_character_states(request),
        )
        plan = validate_state_plan(plan, request["segments"], original)
        self.store.data["appearance_plan"] = plan
        self.store.data.setdefault("appearance_references", {})
        self.store.save()
        refs = (
            initialize_references(
                self.store,
                self.backend,
                segments,
                original,
                self.policy.max_references,
                cancel,
            )
            if self.policy.global_references
            else original
        )
        if self.policy.global_references:
            refs = self._verify_references(refs, original)
        originals = {r["id"]: r for r in original}
        resolved = {}
        reusable = {}
        receipt = self.store.data.get("reference_reuse_source")
        if receipt:
            verify_media(receipt)
            reused = self.store.operation(
                "appearance/reuse_verified",
                {"source": receipt, "plan": plan, "anchors": original},
                lambda: reuse_verified_appearances(receipt, plan, original),
            )
            reusable = reused["references"]
            self.store.data["reused_appearance_audit"] = reused
            self.store.save()
        initial = {}
        for item in plan["timeline"]:
            for b in item["bindings"]:
                initial.setdefault(b["entity"], b["begin_state"])
        ordered = sorted(
            plan["states_by_id"].values(), key=lambda s: s["id"] != initial[s["entity"]]
        )
        for state in ordered:
            if state["id"] in reusable:
                verify_media(reusable[state["id"]]["media"])
                resolved[state["id"]] = copy.deepcopy(reusable[state["id"]])
                self.store.data["appearance_references"] = copy.deepcopy(resolved)
                self.store.save()
                continue
            anchor = originals[state["anchor_id"]]
            key = "appearance/reference/" + digest(state["id"])[:16]
            segment = Segment(
                "reference/" + state["id"], state["description"], 1, (state["entity"],)
            )
            base_prompt = (
                state["prompt"]
                + "\nREQUIRED APPEARANCE STATE (not an event already completed): "
                + str(state["attributes"])
                + ". Preserve the original character face/species/body proportions and art style. "
                "FALSE clothing/prop attributes mean visibly absent; do not retain old straps, pockets or panels as new armor. "
                "Animal anatomy must remain unchanged unless the source explicitly changes it. "
                "The supplied parent reference defines stable identity and art style, NOT the target outfit; replace every conflicting parent garment/prop with the required target state. "
                "Create ONE subject in ONE target appearance, not a contact sheet, collage, lineup or transformation sequence. "
                "Do not preserve the source sheet layout or copy outfits from other views. Show relevant clothing/props clearly, no text. "
                "When an old garment must be absent under new outerwear, show the new outer garment OPEN/UNFASTENED "
                "so the relevant torso and waist are actually visible and absence can be verified. Keep the required new garment present; "
                "do not hide the old garment under opaque armor, substitute a closed vest for a coat, or remove the new garment to pass the check."
            )
            prompt = base_prompt
            current = None
            repair_mode = "generate"
            for attempt in range(self.policy.reference_candidates):
                if cancel:
                    cancel()
                op = key + "/" + str(attempt)
                # Derive each new state from a verified single-state parent. The
                # raw source may mix incompatible outfits in a character sheet;
                # it remains the independent identity/style inspection anchor.
                initial_ref = resolved.get(initial[state["entity"]])
                parent = initial_ref["media"] if initial_ref else anchor["media"]
                image_refs = [parent["path"]]
                if current and repair_mode == "edit":
                    image_refs.append(current["path"])
                image_refs = list(dict.fromkeys(image_refs))[
                    : self.policy.max_references
                ]
                reuse = (attempt == 0 and state["id"] == initial[state["entity"]]
                         and not self.policy.fresh_reference_images)
                target = (
                    self.store.directory
                    / "appearance_references"
                    / (digest(state["id"])[:16] + "-" + str(attempt) + ".png")
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                current = self.store.operation(
                    op + "/render",
                    {
                        "state": state,
                        "prompt": prompt,
                        "references": image_refs,
                        "reuse_original": reuse,
                        "reference_action": "reuse" if reuse else repair_mode,
                    },
                    lambda: (
                        anchor["media"]
                        if reuse
                        else media(
                            self.backend.render_frame(
                                segment, prompt, image_refs, target
                            )
                        )
                    ),
                )
                verify_media(current)
                check = self.store.operation(
                    op + "/inspect",
                    {"state": state, "asset": current, "anchor": anchor},
                    lambda: self.backend.inspect_reference_state(
                        state, current, anchor, segment
                    ),
                )
                self.store.data.setdefault("appearance_candidates", {})[op] = {
                    "state_id": state["id"],
                    "media": current,
                    "inspection": check,
                }
                self.store.save()
                if check["checks"]["critical_passed"]:
                    break
                failed = [
                    r
                    for r in check["checks"]["conditions"]
                    if r["status"] not in ("passed", "not_applicable")
                ]
                unobservable_absence = any(
                    r["status"] == "uncertain"
                    and r["condition"].get("expected") is False
                    and r["condition"]["attribute"].startswith("wearing_")
                    for r in failed
                )
                repair_mode = (
                    "regenerate"
                    if unobservable_absence
                    or any(
                        r["condition"]["attribute"]
                        in ("identity_matches_anchor", "style_matches_anchor")
                        for r in failed
                    )
                    else "edit"
                )
                prompt = (
                    base_prompt
                    + "\nThe previous candidate failed independent visual verification. "
                    + (
                        "Regenerate from the verified identity/style parent; discard the failed candidate style and layout. "
                        if repair_mode == "regenerate"
                        else "Correct the target appearance while preserving original identity and style, not the sheet layout. "
                    )
                    + "Observed defects: "
                    + str(
                        [
                            {
                                "attribute": r["condition"]["attribute"],
                                "observed": r["observed"],
                            }
                            for r in failed
                        ]
                    )
                    + ". Output one coherent target-state character only. Desired full state: "
                    + str(state["attributes"])
                    + ". The FIRST supplied image is the verified identity/style parent; later images cannot override its style. Explicitly remove every parent garment absent in the target state."
                )
            else:
                raise QualityBlocked(
                    "Planned appearance reference could not be verified: " + state["id"]
                )
            ref = dict(
                asdict(
                    Reference(
                        "state:" + state["id"],
                        current["path"],
                        state["description"],
                        (state["entity"],),
                    )
                ),
                media=current,
                appearance_state_id=state["id"],
                appearance_attributes=state["attributes"],
            )
            resolved[state["id"]] = ref
            self.store.data["appearance_references"] = copy.deepcopy(resolved)
            self.store.save()
        self.store.data["appearance_registry_ready"] = True
        self.store.save()
        return refs + list(resolved.values())

    def _verify_references(self, refs, original):
        anchors = [r for r in original if r["entities"]]
        nodes = {n["id"]: n for n in self.store.data["global_reference_graph"]["nodes"]}
        verified = []
        for ref in refs:
            if any(r["id"] == ref["id"] and r["entities"] for r in original):
                verified.append(ref)
                continue
            current = copy.deepcopy(ref)
            node = nodes[ref["id"]]
            for attempt in range(self.policy.reference_candidates):
                op = (
                    "global_references/verify/"
                    + digest(ref["id"])[:16]
                    + "/"
                    + str(attempt)
                )
                request = {"node": node, "asset": current["media"], "anchors": anchors}
                check = self.store.operation(
                    op,
                    request,
                    lambda: self.backend.review_global_reference(
                        node, current["media"], anchors
                    ),
                )
                if (
                    check["style_consistent"]
                    and check["identity_consistent"]
                    and not check["unwanted_entities"]
                ):
                    break
                if attempt + 1 == self.policy.reference_candidates:
                    raise QualityBlocked(
                        "Global reference style/identity verification failed: "
                        + ref["id"]
                    )
                prompt = (
                    "Preserve the intended reference subject and layout: "
                    + node["description"]
                    + ". Match the supplied original character illustration style exactly. Correct only these observed defects: "
                    + "; ".join(check["issues"])
                    + ". Do not insert characters into an empty environment."
                )
                target = (
                    self.store.directory
                    / "global_references"
                    / ("verified-" + digest(op)[:16] + ".png")
                )
                segment = Segment(
                    "reference/" + ref["id"],
                    node["description"],
                    1,
                    tuple(ref["entities"]),
                    tuple(ref["locations"]),
                )
                image_refs = [current["media"]["path"]] + [
                    a["media"]["path"] for a in anchors
                ]
                asset = self.store.operation(
                    op + "/repair",
                    {"prompt": prompt, "references": image_refs},
                    lambda: media(
                        self.backend.render_frame(segment, prompt, image_refs, target)
                    ),
                )
                current.update(path=asset["path"], media=asset)
            verified.append(current)
        self.store.data["verified_global_references"] = verified
        self.store.save()
        return verified

    def bind_context(self, context):
        context = copy.deepcopy(context)
        plan = self.store.data["appearance_plan"]
        resolved = self.store.data["appearance_references"]
        binding = binding_for(plan, context["segment"]["id"])
        active = []
        for b in binding["bindings"]:
            for state_id in (b["begin_state"], b["end_state"]):
                if state_id not in active:
                    active.append(state_id)
        # Current appearance references take precedence over old character outfits.
        # Original identity anchors remain available in the registry/provenance.
        characters = {b["entity"] for b in binding["bindings"]}
        context["references"] = [resolved[s] for s in active] + [
            r
            for r in context["references"]
            if not (set(r["entities"]) & characters)
            and not r.get("appearance_state_id")
        ]
        context.update(
            appearance_binding=binding,
            state_reference_ids={sid: r["id"] for sid, r in resolved.items()},
        )
        return context

    def for_boundary(self, context, refs):
        if "appearance_binding" not in context:
            return context, refs
        phase = "begin" if context.get("frame_role", "begin") == "begin" else "end"
        registry = self.store.data["appearance_references"]
        all_state_paths = {r["media"]["path"] for r in registry.values()}
        desired = [
            registry[b[phase + "_state"]]["media"]["path"]
            for b in context["appearance_binding"]["bindings"]
        ]
        selected = list(
            dict.fromkeys(desired + [p for p in refs if p not in all_state_paths])
        )[: self.policy.max_references]
        enriched = copy.deepcopy(context)
        specs = [
            {
                "entity": b["entity"],
                "state": b[phase]["description"],
                "attributes": b[phase]["attributes"],
            }
            for b in context["appearance_binding"]["bindings"]
        ]
        enriched["decision"]["frame_prompt"] += (
            "\nRequired character appearance at this boundary: "
            + str(specs)
            + ". Current appearance references override historical costumes; preserve character identity."
        )
        return enriched, selected

    def for_video(self, context):
        enriched = copy.deepcopy(context)
        bindings = enriched.get("appearance_binding", {}).get("bindings", [])
        requirements = [
            {
                "entity": b["entity"],
                "begin": b["begin"]["attributes"],
                "end": b["end"]["attributes"],
                "transition_required": b["begin_state"] != b["end_state"],
            }
            for b in bindings
        ]
        enriched["decision"]["video_prompt"] += (
            "\nCharacter-state constraints: "
            + json.dumps(requirements, ensure_ascii=False, separators=(",", ":"))
            + ". Do not repeat transformations in a hold-state segment; do not retain removed garments after a costume change."
        )
        return enriched
