"""Bounded image/video generation with HITS repair and MAPO feedback."""

import copy
import json
from dataclasses import asdict
from memory.contracts.models import average
from memory.assets.files import media, verify_media


class CandidateGenerator:
    def __init__(self, store, backend, policy, references, evaluation, optimizer):
        self.store, self.backend, self.policy = store, backend, policy
        self.references, self.evaluation, self.optimizer = (
            references,
            evaluation,
            optimizer,
        )

    def frame(self, segment, context, key, seed, refs, inherited, cancel):
        context, refs = self.references.for_boundary(context, refs)
        prompt = context["decision"]["frame_prompt"]
        candidates = []
        mode = "reuse" if seed else "generate"
        for attempt in range(1 if inherited else self.policy.frame_candidates):
            if cancel:
                cancel()
            op = key + "/" + str(attempt)
            target = self.store.directory / "media" / (op.replace("/", "-") + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            failed_paths = {c["media"]["path"] for c in candidates}
            allowed_refs = [
                p for p in refs if mode != "regenerate" or p not in failed_paths
            ]
            image_refs = list(
                dict.fromkeys(
                    ([seed] if seed and mode != "regenerate" else []) + allowed_refs
                )
            )[: self.policy.max_references]
            request = {
                "prompt": prompt,
                "context": context,
                "references": image_refs,
                "segment": asdict(segment),
                "frame_action": mode,
            }
            asset = self.store.operation(
                op + "/render",
                request,
                lambda: (
                    media(seed)
                    if attempt == 0 and seed
                    else media(
                        self.backend.render_frame(segment, prompt, image_refs, target)
                    )
                ),
            )
            verify_media(asset)
            candidate = self.evaluation.evaluate("frame", op, asset, segment, request)
            candidate["frame_action"] = mode
            self.store.candidate(op, candidate)
            self.optimizer.learn(
                op, "frame", candidates[-1] if candidates else None, candidate
            )
            candidates.append(candidate)
            if (
                candidate["accepted"]
                and average(candidate["review"]) >= self.policy.early_stop
            ):
                break
            if attempt + 1 < self.policy.frame_candidates and not inherited:
                action = self.store.operation(
                    op + "/hits_action",
                    {"candidate": candidate, "request": request},
                    lambda: self.backend.choose_frame_action(candidate, request),
                )
                mode = action["mode"]
                if mode == "edit":
                    prompt = action["edit_prompt"]
                    seed = asset["path"]
                else:
                    prompt = self.optimizer.refine(op, "frame", candidate, request)
                    seed = ""
        return self.evaluation.choose(candidates)

    def video(self, segment, context, key, frame, end, refs, cancel):
        context = self.references.for_video(context)
        candidates, prompt = [], context["decision"]["video_prompt"]
        for attempt in range(self.policy.video_candidates):
            if cancel:
                cancel()
            op = key + "/video/" + str(attempt)
            target = self.store.directory / "media" / (op.replace("/", "-") + ".mp4")
            target.parent.mkdir(parents=True, exist_ok=True)
            request_context = dict(context, end_media=end["media"] if end else None)
            request = {
                "prompt": prompt,
                "context": request_context,
                "references": refs,
                "segment": asdict(segment),
            }
            asset = self.store.operation(
                op + "/render",
                request,
                lambda: media(
                    self.backend.render_with_end(
                        segment,
                        prompt,
                        frame["media"]["path"],
                        end["media"]["path"] if end else None,
                        target,
                    )
                ),
            )
            verify_media(asset)
            candidate = self.evaluation.evaluate("video", op, asset, segment, request)
            candidate.update(
                mode="interpolation" if end else "extrapolation",
                end_media=end["media"] if end else None,
                candidate_key=op,
                selection_context=json.loads(json.dumps({"segment": asdict(segment), "context": context,
                                   "frame": frame, "end": end})),
            )
            self.store.candidate(op, candidate)
            self.optimizer.learn(
                op, "video", candidates[-1] if candidates else None, candidate
            )
            candidates.append(candidate)
            if (
                candidate["accepted"]
                and average(candidate["review"]) >= self.policy.early_stop
            ):
                break
            if attempt + 1 < self.policy.video_candidates:
                if end is None:
                    # A2RD extrapolation refinement: retain natural final layout, edit it,
                    # then re-synthesize using both boundaries. Never invent an unrelated end layout.
                    bounds = self.evaluation.boundaries(op + "/bounds", asset)
                    feedback = self.store.operation(
                        op + "/end_edit_prompt",
                        candidate,
                        lambda: self.backend.end_edit_prompt(
                            segment, candidate, context
                        ),
                    )
                    end_context = copy.deepcopy(context)
                    end_context.update(frame_role="repair_end")
                    end_context["decision"]["frame_prompt"] = feedback
                    edit_target = target.with_name(target.stem + "-edited-end.png")
                    edited = self.store.operation(
                        op + "/edit_end",
                        {"prompt": feedback, "source": bounds[1], "refs": refs},
                        lambda: media(
                            self.backend.render_frame(
                                segment,
                                feedback,
                                [bounds[1]["path"]]
                                + refs[: self.policy.max_references - 1],
                                edit_target,
                            )
                        ),
                    )
                    end = self.frame(
                        segment,
                        end_context,
                        op + "/verify_end",
                        edited["path"],
                        refs,
                        True,
                        cancel,
                    )
                request["context"] = dict(context, end_media=end["media"])
                prompt = self.optimizer.refine(op, "video", candidate, request)
        return self.evaluation.choose(candidates)
