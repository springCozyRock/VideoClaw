"""Retrieve repair experiences and learn from observed rubric changes."""

import copy
from memory.assets.files import digest
from memory.contracts.validation import validate_prompt
from memory.harness.optimization.semantic import retrieve as semantic_retrieve, ExperienceRepository
from memory.harness.optimization.feedback import label_change


class PromptOptimizer:
    def __init__(self, store, backend, policy):
        self.store, self.backend, self.policy = store, backend, policy

    def refine(self, op, kind, candidate, request):
        saved = self.store.data["operations"].get(op + "/mapo")
        if saved:
            cases = copy.deepcopy(saved["inputs"]["experiences"])
        elif self.policy.mapo:
            pool = (
                self.store.data["seed_experiences"]
                + self.store.data["prompt_experiences"]
            )
            cases = self.store.operation(
                op + "/semantic_retrieve",
                {
                    "pool": copy.deepcopy(pool),
                    "kind": kind,
                    "prompt": candidate["prompt"],
                    "review": candidate["review"],
                },
                lambda: semantic_retrieve(
                    pool,
                    kind,
                    candidate["prompt"],
                    candidate["review"],
                    self.backend.embed_texts,
                ),
            )
        else:
            cases = {}
        data = {"candidate": candidate, "request": request, "experiences": cases}
        return self.store.operation(
            op + "/mapo",
            data,
            lambda: validate_prompt(
                self.backend.refine_with_memory(kind, candidate, request, cases)
            ),
        )

    def learn(self, op, kind, previous, current):
        if not previous or not self.policy.mapo:
            return
        label = label_change(previous["review"]["scores"], current["review"]["scores"])
        if not label or (label == "pos" and current["review"]["hard_failures"]):
            return
        case = {
            "id": op,
            "kind": kind,
            "label": label,
            "original_prompt": previous["prompt"],
            "refined_prompt": current["prompt"],
            "before": previous["review"],
            "after": current["review"],
            "source": {
                "run_fingerprint": self.store.data["fingerprint"],
                "story_fingerprint": digest(self.store.data["inputs"]["segments"]),
                "before_media": previous["media"],
                "after_media": current["media"],
            },
        }
        cases = self.store.data["prompt_experiences"]
        if not any(c["id"] == op for c in cases):
            cases.append(case)
            self.store.save()
        if self.policy.experience_repository:
            ExperienceRepository(self.policy.experience_repository).add(case)
