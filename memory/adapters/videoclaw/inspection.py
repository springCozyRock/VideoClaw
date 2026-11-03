"""Actual-media observations, rubric reviews and independent state predicates."""

import copy
import math
from pathlib import Path
from memory.assets.files import digest
from memory.contracts.models import FRAME_METRICS, VIDEO_METRICS, validate_observation, validate_review, strings
from memory.world.state import evaluate, facts_from_visibility


def normalize_scores(value, metrics=()):
    """Lossless provider field alias, never impute or alter a rubric score."""
    if "scores" not in value and isinstance(value.get("metrics"), dict):
        return dict(value, scores=value["metrics"])
    if "scores" not in value and metrics and all(k in value for k in metrics):
        return dict(value, scores={k: value[k] for k in metrics})
    return value


class Inspection:
    def __init__(self, transport, media):
        self.transport, self.media = transport, media

    def observe(self, kind, path, segment):
        def validate(value):
            if kind == "frame":
                for entity in value.get("entities", []):
                    if not entity.get("motion"):
                        entity["motion"] = (
                            "Motion is not observable from a single still frame."
                        )
            return validate_observation(
                value, 0 if kind == "frame" else segment.duration
            )

        return self.transport.structured(
            "Extract ONLY observable facts from the ACTUAL media, not intentions. "
            "Return entities, spatial_relations, camera and events with the exact schema. Each entity needs "
            "nonempty identity, state, motion and timed evidence. For a still frame motion is not observable; "
            "do not invent movement. Every spatial relation subject/object MUST be an entity id in this same response. "
            "Omit unsupported relations rather than referencing implied unnamed objects. Entity kind is character/object/environment. "
            "Frame timestamps are 0; video times must stay in duration. Use known names where visually justified, "
            "preserve uncertainty and distinguish clothing from anatomy. At most 10 entities and 10 events.",
            {
                "known_names": list(segment.entities) + list(segment.locations),
                "duration": 0 if kind == "frame" else segment.duration,
                "output_schema": {
                    "entities": [
                        {
                            "id": "stable_name",
                            "kind": "character",
                            "identity": "visible stable features",
                            "state": "visible clothing/state",
                            "motion": "not observable in a still frame",
                            "evidence": [
                                {"start": 0, "end": 0, "detail": "visible evidence"}
                            ],
                        }
                    ],
                    "spatial_relations": [],
                    "camera": "visible view/framing",
                    "events": [],
                },
            },
            validate,
            images=[path] if kind == "frame" else [],
            videos=[path] if kind == "video" else [],
        )

    def observe_with_begin(self, path, segment, begin_asset, initial):
        result = self.transport.structured(
            "Extract a HIERARCHICAL visual memory state from this video. The supplied initial_observation "
            "was extracted from its ACTUAL first decoded frame, not a planned frame. Use it to seed stable "
            "entity identities, then inspect the video to correct initial mistakes and supplement visible "
            "changes, newly revealed entities, spatial relations, camera and movement. Return entities "
            "(list of {id,kind,identity,state,motion,evidence}), spatial_relations "
            "(list of {subject,relation,object}), camera (nonempty string), events (list). kind is character, "
            "object or environment. evidence/events contain start,end numeric seconds and detail nonempty "
            "string, within duration. Every entity needs visual evidence. Relations use ids in this result. "
            "Describe initial AND final state in state, and actual evolution in motion. State explicit "
            "uncertainty when obscured or contradictory. Initial-frame evidence establishes only time 0: "
            "never silently copy it as a visible final state. Preserve stable ids when justified, correct "
            "misidentification with explanation. Do not infer hidden events, intentions or goal completion. "
            "The video is sampled at 4fps, so do not invent motion between samples. At most 12 entities "
            "and 12 events. No intended storyline is provided.",
            {
                "known_names": list(segment.entities) + list(segment.locations),
                "duration": segment.duration,
                "initial_observation": initial,
            },
            lambda value: validate_observation(value, segment.duration),
            images=[begin_asset["path"]],
            videos=[path],
        )
        result["extraction"] = {
            "method": "actual_begin_then_video_supplement",
            "begin_media": begin_asset,
            "begin_observation": initial,
        }
        return result

    def review(self, kind, path, observation, request):
        context = request["context"]
        images = list(dict.fromkeys(request["references"]))
        videos = []
        metrics = list(FRAME_METRICS if kind == "frame" else VIDEO_METRICS)
        if kind == "frame":
            images = [path] + [p for p in images if p != path]
            metrics += ["narrative_progression"]
        else:
            images = [context["begin_media"]["path"]] + images
            videos = [path]
            previous = next(
                (
                    r
                    for r in context["history"]
                    if r["segment"]["id"] == context["previous_segment_id"]
                ),
                None,
            )
            if previous and context["decision"]["continuous"]:
                videos.append(previous["video"]["path"])
                images += [previous["end"]["path"]]
            if context.get("end_media"):
                images += [context["end_media"]["path"]]
                metrics += ["frame_fit"]
            # Exact current boundaries supplement uniform video samples.
            exact = self.media.boundaries(
                path,
                Path(path).with_suffix("").with_name(Path(path).stem + "-judge-bounds"),
            )
            images += exact
        images = list(dict.fromkeys(images))
        model_request = copy.deepcopy(request)
        model_context = model_request["context"]
        model_context.pop("storyline", None)
        model_request.pop(
            "segment", None
        )  # Same immutable segment already appears in context.
        model_context["history"] = [
            {
                k: r[k]
                for k in (
                    "segment",
                    "observation",
                    "completed_goals",
                    "unresolved_goals",
                )
                if k in r
            }
            for r in model_context["history"]
        ]
        if kind == "frame":
            model_context["decision"]["goals"] = []
            model_context["decision"].pop("video_prompt", None)
        output_schema = {
            "scores": {k: None for k in metrics},
            "issues": [],
            "hard_failures": [],
            "goals": (
                []
                if kind == "frame"
                else [
                    {
                        "goal": g,
                        "status": "completed/unmet/uncertain",
                        "evidence": "timestamp or uncertainty",
                    }
                    for g in context["decision"]["goals"]
                ]
            ),
        }

        def validate(value):
            value = normalize_scores(value, metrics)
            if set(value.get("scores", {})) != set(metrics):
                raise ValueError("Return exactly these scores: " + ", ".join(metrics))
            extras = {
                k: v
                for k, v in value["scores"].items()
                if k not in (FRAME_METRICS if kind == "frame" else VIDEO_METRICS)
            }
            base = dict(
                value,
                scores={k: v for k, v in value["scores"].items() if k not in extras},
            )
            validate_review(base, kind, context["decision"]["goals"])
            if any(
                type(v) not in (int, float) or not math.isfinite(v) or not 1 <= v <= 10
                for v in extras.values()
            ):
                raise ValueError("Extra rubric scores must be 1..10")
            return value

        return self.transport.structured(
            "Judge the CURRENT frame/video with supplied evidence. Return scores (exact metric names, numeric "
            "1-10), issues (list of strings), hard_failures (list of strings), goals (ordered list of "
            "{goal,status,evidence}, status completed/unmet/uncertain). For frame goals=[]; for video "
            "copy every expected goal verbatim, in order, cite observed timestamps. "
            "Frame role begin: judge only the opening state; a continuous reused boundary need not show "
            "new action yet. Role end/repair_end: judge the planned/observed final state, do not mistake a "
            "legitimate completed transformation for drift. Never require all video actions in one image. "
            "Respect fictional/anime physics, intentional transformations, time jumps and montage. "
            "Identity means stable features appropriate to the planned state, not an unchanging costume. "
            "Judge motion/camera continuity only at a continuous boundary. For deliberate cuts these two "
            "scores are 10 (not applicable) and state this in issues. Do not penalize background anchors for "
            "omitting people; compare relevant entities only. Assess frame_fit when a target end exists. "
            "Unknown critical evidence is uncertain, never completed. Do not mark an entire scene failed "
            "solely because an unobservable smell/thought or exact dialogue cannot be measured visually. "
            "Be critical about missing events, incoherent state changes, repeated actions and visual drift. "
            "Video samples are 4fps; exact first/last frames are also supplied.",
            {
                "kind": kind,
                "frame_role": context.get("frame_role", "begin"),
                "required_score_names": metrics,
                "expected_goals": (
                    context["decision"]["goals"] if kind == "video" else []
                ),
                "observation": observation,
                "request": model_request,
                "source_request_sha256": digest(request),
                "image_paths": images,
                "video_paths": videos,
                "output_schema": output_schema,
            },
            validate,
            images=images,
            videos=videos,
        )

    def inspect_state(
        self, kind, path, requested, segment, references, actual_bounds=None
    ):
        # Mutable facts must be observed without competing reference outfits.
        # Identity/style comparison is a separate call that may see anchors.
        comparison = [s for s in requested if s["attribute"] in ("identity_matches_anchor", "style_matches_anchor")]
        mutable = [s for s in requested if s not in comparison]
        if references and mutable:
            observed = self.inspect_state(kind, path, mutable, segment, [], actual_bounds)
            if comparison:
                compared = self.inspect_state(kind, path, comparison, segment, references, actual_bounds)
                observed["facts"].extend(compared["facts"])
            return observed
        duration = 0 if kind == "frame" else segment.duration
        images = [path] if kind == "frame" else [x["path"] for x in actual_bounds]
        anchor_info = []
        for r in references:
            if r["entities"] or r["locations"]:
                images.append(r["media"]["path"])
                anchor_info.append(
                    {
                        "path": r["media"]["path"],
                        "entities": r["entities"],
                        "locations": r["locations"],
                    }
                )
        images = list(dict.fromkeys(images))
        roles = (
            {path: "ACTUAL state target"}
            if kind == "frame"
            else {
                x["path"]: "ACTUAL boundary " + str(i + 1)
                for i, x in enumerate(actual_bounds)
            }
        )
        image_order = [
            {
                "image_number": i + 1,
                "path": p,
                "role": roles.get(
                    p, "REFERENCE ONLY: stable identity/style, not current state"
                ),
            }
            for i, p in enumerate(images)
        ]
        return self._state_inspection(
            "Independently inspect these named state slots in the ACTUAL media. No intended values are supplied. "
            "Return facts:[{entity,attribute,phase,status,value,reason,evidence:[{start,end,detail}]}], exactly "
            "one for every requested slot. status=observed/unknown/not_visible. observed requires a scalar "
            "value and timed visual evidence; unknown/not_visible require value=null and an explanation. "
            "Read image_order to distinguish ACTUAL media from references. For a frame call, image 1 is "
            "the ONLY state target; all later images are references. Never describe reference clothing as "
            "the actual current outfit. "
            "A hidden apron is UNKNOWN, never absent/false. Assert false only when the relevant body/object "
            "region is sufficiently visible to support absence. not_visible means the entity itself is "
            "visibly outside the shot, not uncertainty about an attribute. "
            "For clothing attributes first describe visible colors, panels, straps, pockets and materials "
            "in visual_description. wearing_ITEM means an EXTERNAL garment, never biological identity. "
            "Animal feathers, fur, beaks or body shape are not evidence of wearing an animal costume. "
            "If garment and anatomy cannot be distinguished, use unknown. "
            "Old and new garments can coexist. Acquiring a suit/armor DOES NOT "
            "prove an apron or other prior garment disappeared. Inspect torso, waist and lower front. "
            "If a remaining panel could be either old clothing or new armor, report unknown instead of "
            "assuming replacement. Do not infer absence from the storyline of a transformation. "
            "Match identity using stable features and size relationships, not requiring initial clothing; compare art style to anchors. "
            "For begin/end inspect the actual decoded boundary images. End facts need evidence at the end, "
            "never copy initial state forward. throughout describes the sampled visible interval; changes "
            "or ambiguity require unknown. Use exact entity/attribute/phase keys. Frame evidence uses 0. "
            "Video is sampled at 4fps; do not invent unsampled motion. Do not copy anchor clothing into facts.",
            {
                "requested_slots": requested,
                "duration": duration,
                "actual_media": path,
                "actual_boundaries": actual_bounds,
                "anchor_images": anchor_info,
                "image_order": image_order,
                "output_schema": {
                    "facts": [
                        {
                            "entity": "requested entity",
                            "attribute": "requested attribute",
                            "phase": "requested phase",
                            "status": "observed/unknown/not_visible",
                            "value": None,
                            "visual_description": "directly visible shape/color/material/region; no transformation narrative",
                            "reason": "visual evidence or uncertainty explanation",
                            "evidence": [
                                {"start": 0, "end": 0, "detail": "visible evidence"}
                            ],
                        }
                    ]
                },
            },
            requested,
            duration,
            images=images,
            videos=[path] if kind == "video" else [],
        )

    def _state_inspection(
        self, instruction, data, requested, duration, images=(), videos=()
    ):
        # The old status enum conflated an invisible entity with an absent garment.
        # These independent flags make an empty hand a visible negative observation.
        instruction += (
            " RESPONSE SCHEMA OVERRIDE: do NOT output status. For each requested slot output "
            "entity_visible (true when the named character is in the ACTUAL target, false ONLY when that CHARACTER "
            "is outside the shot, null when entity visibility itself is uncertain); attribute_observable (boolean); "
            "value; visual_description; reason; evidence; and the exact entity,attribute,phase identifiers. "
            "The program derives status. A visible character with bare face and no glasses has entity_visible=true, "
            "attribute_observable=true, value=false for wearing_glasses. Visible EMPTY hands similarly establish "
            "holding_sword=false, not an unobservable property. A visible torso with clearly absent outer garment "
            "can establish wearing_coat=false. If the torso is occluded, entity_visible=true but "
            "attribute_observable=false,value=null. If the CHARACTER is offscreen, entity_visible=false, "
            "attribute_observable=false,value=null. Never mark entity_visible=false because an ITEM is absent. "
            "These are semantic examples only; inspect each actual requested attribute independently. "
            "For scale use a definite canonical label tiny/small/normal/large/giant when size is visually supported. "
            "Use giant for building-scale enlargement, not merely a larger portrait on a character sheet. "
            "Do not confuse differently sized drawings on a sheet with real-world size evidence. "
            "Do not infer absence under opaque clothing. Original reference images do not establish actual state."
        )
        payload = dict(
            data,
            output_schema={
                "facts": [
                    {
                        "entity": "requested entity",
                        "attribute": "requested attribute",
                        "phase": "requested phase",
                        "entity_visible": True,
                        "attribute_observable": True,
                        "value": False,
                        "visual_description": "direct actual visual evidence",
                        "reason": "explain assessment or uncertainty",
                        "evidence": [
                            {"start": 0, "end": 0, "detail": "visible evidence"}
                        ],
                    }
                ]
            },
        )
        if duration:
            instruction += (
                " For video throughout slots, provide visibility_intervals:[{start,end,visibility}] "
                "in chronological order, covering 0..duration without gaps or overlap. visibility=visible/offscreen/uncertain. "
                "A close-up of another character can legitimately take this entity offscreen. entity_visible=true means "
                "the entity appears at least once. Assess identity/style ONLY across ALL its visible windows; evidence "
                "timestamps cover those windows, not offscreen periods. Do not fabricate boundary evidence when the "
                "entity is offscreen. Split evidence ranges across offscreen gaps. If visibility or an attribute is "
                "uncertain in any visible interval, attribute_observable=false,value=null. A fully offscreen entity "
                "has entity_visible=false. Do not call an obscured entity offscreen merely to bypass uncertainty."
            )
            payload["output_schema"]["facts"][0]["visibility_intervals"] = [
                {
                    "start": 0,
                    "end": duration,
                    "visibility": "visible/offscreen/uncertain",
                }
            ]
        def validate_facts(value):
            import re
            for fact in value.get("facts", []):
                # A model sometimes corrects its rationale but leaves the JSON boolean stale.
                # Reject and request schema correction; never flip the observation ourselves.
                claims = re.findall(r"\bvalue\s*(?:=|should be|must be)\s*(true|false)\b", str(fact.get("reason", "")), re.I)
                if claims and type(fact.get("value")) is bool and fact["value"] != (claims[-1].lower() == "true"):
                    raise ValueError("Observation contradicts its final stated value for " + str(fact.get("entity")) + "/" + str(fact.get("attribute")) + ". Reinspect the ACTUAL first image and return consistent value, description and reason; references are not the target.")
            return facts_from_visibility(value, requested, duration)

        return self.transport.structured(
            instruction + " Return final consistent judgments only, without draft reasoning or self-correction prose. The example value=false is a placeholder, not a default answer.",
            payload,
            validate_facts,
            images=images,
            videos=videos,
        )

    def inspect_reference_state(self, state, asset, anchor, segment):
        requested = [
            {"entity": state["entity"], "attribute": a, "phase": "end"}
            for a in state["attributes"]
        ]
        requested += [
            {"entity": state["entity"], "attribute": a, "phase": "end"}
            for a in ("identity_matches_anchor", "style_matches_anchor")
        ]
        observed = self.inspect_state(
            "frame", asset["path"], requested, segment, [anchor]
        )
        conditions = [
            dict(
                s,
                id=str(i),
                expected=state["attributes"].get(s["attribute"], True),
                critical=True,
                visibility="required",
                goal=None,
            )
            for i, s in enumerate(requested)
        ]
        return {
            "observation": observed,
            "checks": evaluate({"conditions": conditions}, observed, requested),
        }

    def review_global_reference(self, node, asset, anchors):
        def validate(value):
            for k in ("style_consistent", "identity_consistent", "unwanted_entities"):
                if type(value.get(k)) is not bool:
                    raise ValueError(
                        "Explicit reference verification booleans required"
                    )
            strings(value.get("issues"), "issues")
            return value

        return self.transport.structured(
            "Verify this generated GLOBAL reference against the supplied original character "
            "style/identity anchors. Return style_consistent, identity_consistent, unwanted_entities booleans, "
            "issues:list. For an empty environment design, identity_consistent=true is not applicable; "
            "unwanted_entities=true if it unnecessarily inserts characters. Check hand-drawn/watercolor "
            "versus photographic/3D rendering, linework and materials; matching colors alone is insufficient. "
            "For a planned transformed character, respect stated costume changes but preserve stable identity.",
            {
                "node": node,
                "candidate": asset,
                "anchors": [
                    {"id": r["id"], "entities": r["entities"]} for r in anchors
                ],
            },
            validate,
            images=[asset["path"]] + [r["media"]["path"] for r in anchors],
        )
