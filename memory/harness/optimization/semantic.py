"""Dense MAPO retrieval and provenance-checked, opt-in cross-story seed storage."""

import copy
import json
import math
from pathlib import Path
from memory.harness.optimization.feedback import label_change
from memory.assets.checkpoint import Checkpoint
from memory.assets.files import digest, verify_media


def validate_case(case):
    if case.get("kind") not in ("frame", "video") or case.get("label") not in (
        "pos",
        "neg",
    ):
        raise ValueError("Invalid experience modality/label")
    for k in ("id", "original_prompt", "refined_prompt"):
        if not isinstance(case.get(k), str) or not case[k].strip():
            raise ValueError("Missing experience text")
    for review in (case["before"], case["after"]):
        if not review.get("scores") or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 1 <= v <= 10
            for v in review["scores"].values()
        ):
            raise ValueError("Invalid source rubric scores")
    if label_change(case["before"]["scores"], case["after"]["scores"]) != case["label"]:
        raise ValueError("Seed label is not supported by its original rubric changes")
    source = case.get("source", {})
    if not source.get("story_fingerprint") or not source.get("run_fingerprint"):
        raise ValueError("Seed must identify its actual source story/run")
    for key in ("before_media", "after_media"):
        verify_media(source[key])
    if case["label"] == "pos" and case["after"].get("hard_failures"):
        raise ValueError(
            "Do not seed a claimed successful repair with unresolved hard failures"
        )
    return case


class ExperienceRepository:
    def __init__(self, path):
        self.path = Path(path)

    def add(self, case):
        validate_case(case)
        key = digest(case)
        with Checkpoint(self.path) as store:
            store.data.setdefault("cases", {})[key] = copy.deepcopy(case)
            store.save()
        return key

    def snapshot(self, exclude_story):
        with Checkpoint(self.path) as store:
            values = copy.deepcopy(list(store.data.get("cases", {}).values()))
        return [
            validate_case(c)
            for c in values
            if c["source"]["story_fingerprint"] != exclude_story
        ]


def embedding_text(prompt, review):
    return json.dumps(
        {
            "prompt": prompt,
            "scores": review["scores"],
            "issues": review.get("issues", []),
            "hard_failures": review.get("hard_failures", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def cosine(a, b):
    if (
        len(a) != len(b)
        or not a
        or any(
            type(x) not in (int, float) or not math.isfinite(x)
            for x in list(a) + list(b)
        )
    ):
        raise ValueError("Incompatible or invalid dense vectors")
    denom = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    if not denom:
        raise ValueError("Zero semantic embedding")
    return sum(x * y for x, y in zip(a, b)) / denom


def retrieve(cases, kind, prompt, review, embed, top_k=2):
    eligible = [c for c in cases if c["kind"] == kind]
    if not eligible:
        return {"pos": [], "neg": []}
    texts = [embedding_text(prompt, review)] + [
        embedding_text(c["original_prompt"], c["before"]) for c in eligible
    ]
    vectors = embed(texts)
    if len(vectors) != len(texts):
        raise ValueError("Embedding count mismatch")
    ranked = sorted(
        zip(eligible, vectors[1:]),
        key=lambda item: (-cosine(vectors[0], item[1]), item[0]["id"]),
    )
    return {
        label: [copy.deepcopy(c) for c, v in ranked if c["label"] == label][:top_k]
        for label in ("pos", "neg")
    }


class CachedEmbeddings:
    """No automatic repeat of unknown paid outcomes, and no lexical fallback."""

    def __init__(self, path, transport, model="text-embedding-v4", dimensions=1024):
        self.path, self.transport = Path(path), transport
        self.model, self.dimensions = model, dimensions

    def __call__(self, texts):
        vectors = []
        from memory.assets.journal import ArtifactJournal
        from contextlib import nullcontext
        with nullcontext(ArtifactJournal(self.path)) as store:
            for offset in range(0, len(texts), 10):
                batch = texts[offset : offset + 10]
                request = {
                    "model": self.model,
                    "input": batch,
                    "dimensions": self.dimensions,
                    "encoding_format": "float",
                }

                def call():
                    response = self.transport(request)
                    data = sorted(
                        response.get("data", []), key=lambda row: row["index"]
                    )
                    if [r["index"] for r in data] != list(range(len(batch))):
                        raise ValueError("Embedding response indices mismatch")
                    result = [r["embedding"] for r in data]
                    for vector in result:
                        if len(vector) != self.dimensions:
                            raise ValueError("Embedding dimension mismatch")
                        cosine(vector, vector)
                    return {
                        "vectors": result,
                        "usage": response.get("usage"),
                        "response_model": response.get("model"),
                    }

                result = store.operation(digest(request), request, call)
                vectors.extend(result["vectors"])
        return vectors
