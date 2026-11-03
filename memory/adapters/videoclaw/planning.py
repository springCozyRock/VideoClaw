"""Source-grounded appearance planning, segment decisions, retrieval and repair."""

import copy
from memory.contracts.validation import validate_decision, validate_prompt
from memory.contracts.models import strings
from memory.world.state import validate_contract, durable_contract
from memory.world.references.character_states import state_contract, merge_environment_plan, compile_state_changes
from memory.world.references.shots import validate_selection


class Planning:
    def __init__(self, transport):
        self.transport = transport

    def select_context(self, query):
        def validate(value):
            for key in ("segment_ids", "reference_ids"):
                strings(value.get(key), key)
                if len(value[key]) != len(set(value[key])):
                    raise ValueError("Duplicate retrieval ids")
            if (
                not set(value["segment_ids"]) <= {p["id"] for p in query["previous"]}
                or not set(value["reference_ids"])
                <= {p["id"] for p in query["references"]}
                or len(value["segment_ids"]) > query["top_k"]
                or len(value["reference_ids"]) > query["max_references"]
            ):
                raise ValueError("Use only provided ids within the retrieval limits")
            return value

        return self.transport.structured(
            "Retrieve narratively relevant PRIOR segments and global references for the CURRENT segment. "
            "Return segment_ids (at most top_k), reference_ids (at most max_references), and reason (string). "
            "Use only listed ids. Match entities despite linguistic variants, but do not merge different people. "
            "Prefer latest relevant observed states, and older identity/environment anchors for reappearances. "
            "Do not use an outdated costume/state to undo an explicitly planned transformation. "
            "Return empty segment_ids when there is no history. Select references relevant to all characters, "
            "objects and environments that appear during this segment, not just its first frame.",
            query,
            validate,
        )

    def plan_character_states(self, request):
        data = dict(
            request,
            output_schema={
                "characters": [
                    {
                        "entity": "exact character name",
                        "anchor_id": "original reference id",
                        "identity_description": "Stable face/species/body proportions and art style; exclude mutable outfit and pose",
                        "initial_attributes": {},
                        "source_quotes": [
                            {
                                "segment_id": "id",
                                "quote": "exact substring establishing initial design",
                            }
                        ],
                    }
                ],
                "changes": [],
            },
        )
        instruction = (
            "Extract the MINIMAL durable character appearance design facts from the ENTIRE immutable story. "
            "Return characters and changes. The PROGRAM constructs all states and segment bindings by applying changes; "
            "do not enumerate states, shots, actions or a full timeline yourself. Define every scripted character exactly once, "
            "bound to its own supplied original identity anchor. Inspect source_image_order images for stable identity/style. "
            "Each character has entity,anchor_id,identity_description,initial_attributes,source_quotes. "
            "initial_attributes is a small map of concrete source-supported durable attributes. Use lowercase item predicates "
            "such as wearing_red_hat or holding_sword, boolean values; the suffix names an ACTUAL item. Never use ITEM, "
            "generic item/object, null, pose, expression, location, motion or VFX properties. Attributes form/scale are only "
            "for an explicit transformation or growth/shrink event, not stable species or big/little names. "
            "For a character with no costume/form/lasting possession change, use initial_attributes={} and no changes; "
            "describe its stable design in identity_description. Emotions, sitting, kneeling, sleeping, illness and camera "
            "views are handled by the shot review; they are NOT new appearance designs. Stable clothing can remain "
            "in the identity description only if it NEVER changes in this story. Use at most six distinct appearances. "
            "changes is [] unless the CURRENT shot explicitly changes costume, form, size or durable possession. "
            "Each change is {segment_id,entity,phase,attributes,quote}; phase=begin only if the segment opens with a "
            "changed appearance, end for a transformation happening DURING this segment. attributes contains only "
            "changed properties, with exact SAME keys as initial_attributes. Declare every changed attribute initial value "
            "explicitly, including false for an item not initially present. Never guess missing initial values. "
            "Before returning, compute the union of changed attribute keys for EACH entity and ensure every key "
            "also appears in that entity's initial_attributes with a source-supported value. "
            "If the story explicitly shrinks or grows a character, scale IS mutable: its initial scale belongs "
            "in initial_attributes even when that same size also appears in its name or biography. "
            "The rule excluding stable big/little names applies ONLY when no size-change event exists. "
            "quote must be an EXACT substring of the CURRENT shot text after 分镜列表. Character biographies can establish "
            "initial appearances but cannot trigger later transformations. Every initial design needs literal source_quotes "
            "with segment_id and quote from its source context. No ellipses or paraphrase. "
            "Removing a garment and acquiring another are separate predicates. Return to daily life does not automatically "
            "restore an old garment; only an explicit shot change can do that. Distinguish biological identity from costume: "
            "feathers are not an animal suit. A required trench coat is not generic armor. Do not invent or rewrite any story event. "
            "Do not create appearance changes for synonymous descriptions of the same unchanged outfit. "
            "For changes output concrete JSON objects with the six named fields; the empty changes example means no changes "
            "only when the story truly has none. Keep the response concise and in source language."
        )
        image_sources = [r for r in request["sources"] if r["entities"]]
        data["source_image_order"] = [
            {"image_number": i + 1, "id": r["id"], "entities": r["entities"]}
            for i, r in enumerate(image_sources)
        ]
        for _ in range(2):
            plan = self.transport.structured(
                instruction,
                data,
                lambda v: compile_state_changes(
                    v, request["segments"], request["sources"]
                ),
                images=[r["media"]["path"] for r in image_sources],
            )

            def audit_schema(v):
                if type(v.get("faithful")) is not bool:
                    raise ValueError("Appearance audit needs faithful boolean")
                strings(v.get("issues"), "issues")
                return v

            audit = self.transport.structured(
                "Audit ONLY this planned appearance registry and timeline against the immutable story. "
                "Return faithful and issues. Check character identity, separate source-required daily/battle/return appearances, "
                "explicit removals as well as acquisitions, no repeated transition, no premature final state at a segment opening, "
                "and no spontaneous restoration of removed garments/props. Mere daily return does not imply re-wearing removed items. "
                "Keep biological identity distinct from costume. Reject unsupported persistent visual requirements. "
                "Do not demand transient poses or VFX in this registry. Different camera views are not new appearances. "
                "Accept a faithful minimal registry; do not invent new constraints.",
                {
                    "segments": request["segments"],
                    "sources": request["sources"],
                    "plan": plan,
                    "output_schema": {"faithful": True, "issues": []},
                },
                audit_schema,
            )
            if audit["faithful"]:
                return dict(plan, audit=audit)
            data["correction"] = audit
            data["previous_extraction"] = plan["compiled_from_source_changes"]
        raise ValueError(
            "Appearance plan failed source audit: " + "; ".join(audit["issues"])
        )

    def plan_global_references(self, request):
        return self.transport.structured(
            "Plan only necessary environment/object reference proposals for the entire story. Return nodes:[]. "
            "ALL supplied source anchors are retained automatically in code; do not list character anchors or character variants. "
            "Character appearance designs are managed by a separate registry. Each proposed node has "
            "id,action,description,entities:[],locations:list,depends_on:list,prompt,reason. "
            "Use action=generate and an existing environment id to restyle an incompatible supplied environment, "
            "or a new distinct id for at most max_extra_assets necessary recurring environments/objects. "
            "Return nodes=[] if supplied environments already suffice. Do not add redundant scene copies. "
            "Condition environments on supplied character/style anchors to match their artwork but do not insert "
            "characters into empty environment references. Dependencies use existing source ids or proposed ids; "
            "at most max_dependencies each, acyclic. Describe ONE reference image, no montage, text or completed "
            "story event. Preserve the immutable storyline and source location names.",
            dict(request, output_schema={"nodes": []}),
            lambda value: merge_environment_plan(
                value, request["sources"], request["max_dependencies"]
            ),
            images=[s["media"]["path"] for s in request["sources"]],
        )

    def prepare(self, context):
        if "appearance_binding" in context:
            adapted = copy.deepcopy(context)
            constraints = []
            for binding in context["appearance_binding"]["bindings"]:
                constraints.append(
                    {
                        "entity": binding["entity"],
                        "opening_state": binding["begin"],
                        "ending_state": binding["end"],
                        "transition_quote": binding.get("transition_quote"),
                    }
                )
            # Keep planned requirements separate from observations in the source audit.
            adapted["persistent_requirements"] = list(
                adapted.get("persistent_requirements", [])
            ) + [
                {
                    "type": "global_appearance_binding",
                    "requirements": constraints,
                    "instruction": "Use these preplanned opening/end states and their supplied visual references. State assets are designs, not evidence that a transition already occurred. Preserve stable identity, but do not import an old reference outfit. Never repeat a transition in a hold-state segment.",
                }
            ]
            context = adapted

        def validate(value):
            if value.get("segment_id") != context["segment"]["id"]:
                raise ValueError("segment_id MUST equal " + context["segment"]["id"])
            validate_decision(value, bool(context["previous_segment_id"]))
            for key in ("no_new_environment", "next_contiguous"):
                if type(value.get(key)) is not bool:
                    raise ValueError("Require boolean " + key)
            if (
                not isinstance(value.get("end_frame_prompt"), str)
                or not value["end_frame_prompt"].strip()
            ):
                raise ValueError("Require end_frame_prompt")
            return value

        instruction = (
            "Plan ONLY current_segment_to_generate for autoregressive video synthesis. Do NOT generate the "
            "lookahead segment instead. Return segment_id (copy current_segment_to_generate.id EXACTLY), "
            "continuous (boolean, whether "
            "its opening continues immediately from the previous selected actual ending), continuity_reason, "
            "goals (nonempty ordered strings: concise VISUALLY observable required actions/states), "
            "allowed_changes (strings), frame_prompt, video_prompt, end_frame_prompt, "
            "no_new_environment (boolean: this segment never transitions to a new established environment), "
            "next_contiguous (boolean: next segment continues in space/time, true for final segment). "
            "These last two booleans select extrapolation versus interpolation. Preserve canonical shot "
            "order and duration. Do not demand visual verification of abstract thoughts, fragrances, or spoken "
            "words; preserve provided dialogue in video_prompt, but goals assess visually observable content. "
            "frame_prompt describes a SINGLE static opening instant and body pose. Do not ask a still "
            "image to show ongoing temporal movement. No collage or prematurely completed action. "
            "end_frame_prompt describes ONE plausible final boundary aligned with the next opening if "
            "appropriate, never executing next-segment actions prematurely. Preserve the current segment full "
            "event chain in video_prompt; time jumps/hard cuts are allowed when the script requires them. "
            "Identify invariant identity features versus legitimate costume, age, scale, weather or location "
            "changes. Global reference images may show initial costumes: explicitly override them for planned "
            "transformations. Selected history may contain quality defects; use its observation as evidence "
            "of the actual video, but correct accidental drift against global identity anchors. "
            "Keep prompts under 1800 Chinese characters each. Use the same style and language as the segment."
        )
        instruction += (
            " Narrative cause is not spatial-temporal continuity: time/location jumps require "
            "continuous=false. Where a translated summary conflicts with an explicitly embedded "
            "original canonical shot, follow the canonical shot. Narration is audio, not subtitles; "
            "keep audio outside visually verified goals. A continuous opening must remain compatible "
            "with the actual previous ending, before new actions occur."
        )
        data = {
            "history": context["history"],
            "references": context["references"],
            "previous_segment_id": context["previous_segment_id"],
            "lookahead_not_current": context["next_segment"],
            "current_segment_to_generate": context["segment"],
        }
        if "world_state" in context:
            data["observed_world_state_with_provenance"] = context["world_state"]
            instruction += (
                " World-state rows describe actual observations, including defects; they are not "
                "new storyline requirements. Never restore an outdated costume or silently treat "
                "an uncertain attribute as absent. Preserve legitimate completed changes."
            )
        if "persistent_requirements" in context:
            data["persistent_requirements_not_observations"] = context[
                "persistent_requirements"
            ]
            instruction += (
                " Retain persistent costume/form/possession requirements until the CURRENT shot "
                "explicitly changes them. Generic original character descriptions do not restore "
                "removed garments. Include relevant retained constraints in generation prompts; "
                "these requirements are intentions, never evidence that they were achieved."
            )
        for attempt in range(2):
            proposal = self.transport.structured(instruction, data, validate)

            def audit_schema(value):
                if type(value.get("faithful")) is not bool:
                    raise ValueError("faithful must be boolean")
                strings(value.get("issues"), "issues")
                return value

            audit = self.transport.structured(
                "Audit whether this proposed generation plan faithfully implements the immutable CURRENT "
                "segment. Return faithful:boolean and issues:list of strings. Check that goals/video_prompt "
                "cover the current required events, do not substitute a different scene or skip a required "
                "transformation. The opening frame must belong to this segment. A final boundary may anticipate "
                "the next opening but must not perform future actions prematurely. Brief extra visual details "
                "and omission of nonvisual thoughts/smells from goals are acceptable. Do not rewrite the source.",
                {
                    "immutable_current_segment": context["segment"],
                    "proposal": proposal,
                    "previous": next(
                        (
                            {"segment": r["segment"], "observation": r["observation"]}
                            for r in context["history"]
                            if r["segment"]["id"] == context["previous_segment_id"]
                        ),
                        None,
                    ),
                    "next_segment": context["next_segment"],
                    **(
                        {"persistent_requirements": context["persistent_requirements"]}
                        if "persistent_requirements" in context
                        else {}
                    ),
                    "audit_rules": "Check immediate spatial/temporal continuity, not merely causal story continuation. "
                    "Honor embedded canonical source over conflicting translation. Audio narration is "
                    "compatible with no subtitles; framing is visually observable. Accept equivalent "
                    "descriptions of the same moment without inventing extra requirements.",
                },
                audit_schema,
            )
            if audit["faithful"]:
                return dict(
                    proposal,
                    plan_audit=audit,
                    **(
                        {
                            "appearance_binding": copy.deepcopy(
                                context["appearance_binding"]
                            )
                        }
                        if "appearance_binding" in context
                        else {}
                    )
                )
            data["mandatory_plan_correction"] = audit
        raise ValueError(
            "Plan failed immutable segment audit: " + "; ".join(audit["issues"])
        )

    def prepare_state_contract(self, context, decision):
        if "appearance_binding" in context:
            return state_contract(
                context["appearance_binding"], context["state_reference_ids"]
            )
        full_source = context["segment"]["context"]
        # VideoClaw embeds the original character biography before current shots.
        # It may describe an OLD outfit. Mutable requirements must quote this
        # segment's actions, never turn that biography into a new transition.
        marker = "\n分镜列表：\n"
        source = (
            full_source.split(marker, 1)[1] if marker in full_source else full_source
        )
        entities = context["known_entities"]
        refs = context["references"]
        payload = {
            "current_source": source,
            "goals": decision["goals"],
            "stable_entities": entities,
            "references": [
                {"id": r["id"], "entities": r["entities"], "locations": r["locations"]}
                for r in refs
            ],
            "observed_world_state": context.get("world_state", []),
            "persistent_requirements": context.get("persistent_requirements", []),
            "output_schema": {
                "conditions": [
                    {
                        "id": "unique_condition_id",
                        "entity": "exact stable entity",
                        "attribute": "snake_case_property",
                        "expected": "source-derived scalar",
                        "phase": "begin/end/throughout",
                        "critical": True,
                        "visibility": "required/when_visible",
                        "persistence": "segment/until_changed",
                        "goal": None,
                        "source": {
                            "type": "script",
                            "quote": "literal current-source quote",
                        },
                    }
                ]
            },
        }
        instruction = (
            "Derive atomic visual state CONDITIONS for this CURRENT source segment, preserving its storyline. "
            "Return conditions:[{id,entity,attribute,expected,phase,critical,visibility,persistence,goal,source}]. "
            "entity must be an exact stable_entities value. attribute is a stable English snake_case predicate, "
            "supported attributes are wearing_ITEM, holding_ITEM, carrying_ITEM, form, scale, sleep_state, "
            "identity_matches_anchor, style_matches_anchor. expected is a scalar. "
            "phase is begin/end/throughout. throughout must not contradict ANY begin/end value. "
            "Use only durable entity states plus identity/style. Omit transient electricity, lighting, "
            "background VFX and inferred mandatory body-part visibility; the main review covers those. "
            "Separate initial and final values for explicit transitions: "
            "removing an apron requires wearing_apron=false at end, not merely wearing_armor=true. "
            "Include explicit removals, acquisitions, size/state changes, and identity/style constraints. "
            "Never demand a later event at the opening. Avoid abstract emotions or audio-only conditions. "
            "critical is true for explicit required visible state changes and identity/style. "
            "visibility is required for scripted visible outcomes, when_visible for identity/style of "
            "characters that may legitimately be offscreen. goal is an exact associated goal string or null. "
            "source={type:script,quote:EXACT contiguous substring of current_source} for mutable states. "
            "Never join snippets with ellipses or paraphrase quotes. "
            "For identity/style, use source={type:reference,reference_id:listed id}, attribute "
            "identity_matches_anchor/style_matches_anchor, expected=true; these refer to stable features "
            "and art style, not unchanged clothes. Never invent a transition from an old observation. "
            "Observed errors remain errors, not new requirements. At most 40 conditions."
        )
        instruction += (
            " persistence=until_changed for enduring costume/form/possession changes, segment for transient actions. "
            "Reuse the EXACT attribute names of supplied persistent_requirements for the same property. "
            "Those are prior intended requirements, not visual observations. Generic character background descriptions "
            "do not undo them. Only an explicit NEW change in current shot actions may override them. "
            "Do not reintroduce a removed garment at the beginning just because the original character wore it. "
            "Omit an unchanged inherited predicate: the controller will retain it with original provenance."
        )
        for attempt in range(2):
            contract = self.transport.structured(
                instruction,
                payload,
                lambda value: validate_contract(
                    durable_contract(value),
                    entities,
                    decision["goals"],
                    source,
                    [r["id"] for r in refs],
                ),
            )

            def check(value):
                if type(value.get("faithful_and_complete")) is not bool:
                    raise ValueError("Contract audit must state faithful_and_complete")
                strings(value.get("issues"), "issues")
                return value

            audit = self.transport.structured(
                "Audit ONLY the atomic conditions in this state contract against the source. "
                "Return faithful_and_complete:boolean and issues:list. Accept if there is no concrete state error. "
                "Only the declared schema_scope is covered here. out_of_scope_conditions are recorded proposals "
                "for motion/VFX/scene actions, assessed by the separate primary video review; do not demand them here. "
                "Structure, exact quotes, duplicate slots and contradictory throughout values are already checked in code. "
                "Check (1) an explicit removed item has expected=false at end, (2) required acquired costume/form "
                "has its final predicate, (3) no condition asserts an unsupported or premature state, "
                "(4) persistent requirements are overridden only by a NEW explicit current shot change. "
                "A pair wearing_apron=true at begin and false at end is a COMPLETE removal specification. "
                "Acquiring armor is separately satisfied by its own predicate. Do not demand extra causal links, "
                "transition fields or duplicate conditions. Multiple atomic conditions may link to the SAME goal. "
                "Do NOT re-audit or rewrite the supplied goal labels or old generation plan: they are identifiers. "
                "Do not reject harmless framing descriptions in those labels. Report only condition IDs and "
                "specific unsupported values or exact missing scripted state changes. Stable identity is checked "
                "against anchors, not mandatory visibility of every body part. Generic character background "
                "cannot undo persistent clothing changes. Enduring costume changes need persistence=until_changed.",
                {
                    "source": source,
                    "goals": decision["goals"],
                    "contract": contract,
                    "persistent_requirements": context.get(
                        "persistent_requirements", []
                    ),
                    "output_schema": {"faithful_and_complete": True, "issues": []},
                },
                check,
            )
            if audit["faithful_and_complete"]:
                return dict(contract, audit=audit)
            payload["correction"] = audit
        raise ValueError("State contract failed source audit")

    def choose_frame_action(self, candidate, request):
        def validate(value):
            if value.get("mode") not in ("edit", "regenerate"):
                raise ValueError("HITS requires explicit edit or regenerate")
            for key in ("reason", "single_issue"):
                if not isinstance(value.get(key), str) or not value[key].strip():
                    raise ValueError("HITS requires a concrete issue and reason")
            if value["mode"] == "edit":
                validate_prompt(value.get("edit_prompt"))
            return value

        return self.transport.structured(
            "Choose the HITS action for this failed boundary frame. Return mode:edit/regenerate, "
            "reason, single_issue, edit_prompt. edit_prompt is required only for edit; for regenerate it may be null/empty because MAPO builds the new prompt. Use edit for ONE localized fix retaining correct identity/layout; "
            "use regenerate for fundamental scene/identity/layout failure. For edit, target the most important "
            "concrete failed condition, including removal of forbidden clothing/props. Never mark a fix successful "
            "before observing the new image. Regenerate will build from reference anchors without the failed image.",
            {"candidate": candidate, "request": request},
            validate,
        )

    def prepare_next_boundary(self, context, next_context):
        def validate(value):
            validate_prompt(value.get("frame_prompt"))
            return value

        return self.transport.structured(
            "Plan ONE static boundary for interpolation using the separately retrieved NEXT "
            "segment context. It should bridge the current ending into the next opening, without performing "
            "next-segment actions early or omitting current required events. Preserve current completed state "
            "changes. Return frame_prompt:string and reason:string. No collage or action montage in one image.",
            {"current": context, "next_retrieved_context": next_context},
            validate,
        )

    def select_temporal_history(self, context, candidates):
        def validate(value):
            if value.get("segment_id") is not None and value["segment_id"] not in {
                c["id"] for c in candidates
            }:
                raise ValueError("Temporal retrieval chose nonexistent prior segment")
            if not isinstance(value.get("reason"), str) or not value["reason"].strip():
                raise ValueError("Temporal retrieval reason required")
            return value

        return self.transport.structured(
            "Identify a PRIOR video whose event timeline is immediately resumed by the "
            "current/next transition, including a non-adjacent scene after a cutaway. Return segment_id or null, "
            "and reason. Mere shared identity/location is insufficient. Do not resurrect an outdated state "
            "after later canonical changes. All choices must come from supplied previously generated segments.",
            {
                "current": context["segment"],
                "next": context.get("next_segment"),
                "candidates": candidates,
            },
            validate,
        )

    def select_historical_boundary(self, context, source_record, extracted):
        return self.transport.structured(
            "Choose the actual prior shot-end image best continuing into the NEXT opening "
            "for this explicitly retrieved historical scene. Return shot_id and reason. Do not choose a state "
            "that undoes later completed changes. IDs refer to real extracted images, not invented frames.",
            {
                "current": context["segment"],
                "next": context.get("next_segment"),
                "historical_segment": source_record["segment"],
                "historical_observation": source_record["observation"],
                "shot_end_candidates": extracted["candidates"],
            },
            lambda value: validate_selection(value, extracted["candidates"]),
            images=[c["media"]["path"] for c in extracted["candidates"]],
        )

    def refine_with_memory(self, kind, candidate, request, cases):
        def validate(v):
            validate_prompt(v.get("prompt"))
            return v["prompt"]

        return self.transport.structured(
            "Memory-augmented prompt optimization. Return {lessons: string, root_cause: string, prompt: string}. "
            "Contrast relevant positive and negative refinement cases (if any), derive actionable lessons, "
            "identify root causes in the current rubric, then make targeted changes. Preserve required story "
            "events, identity, intended transformations, duration and dialogue. Never remove a hard goal to "
            "increase scores. For video with fixed begin/end, respect both endpoints and fit actions between "
            "them. For image edits target the highest-impact defect while retaining correct layout. "
            "Keep prompt under 1800 Chinese characters. Do not claim a correction already succeeded.",
            {
                "kind": kind,
                "candidate": candidate,
                "request": request,
                "experiences": cases,
            },
            validate,
        )

    def end_edit_prompt(self, segment, candidate, context):
        def validate(v):
            return validate_prompt(v.get("prompt"))

        return self.transport.structured(
            "Return {prompt: string} for a targeted EDIT of the actual last frame of this video. "
            "Preserve the actual composition, viewpoint, positions and natural layout progression. "
            "Repair the highest-impact identity/state defect flagged by evaluation. Respect all intentional "
            "transformations already completed by this point; do not reset costumes/scale to initial references. "
            "If there is no appearance defect, explicitly preserve this final frame. No collage or scene reset.",
            {"segment": segment.context, "candidate": candidate, "context": context},
            validate,
        )
