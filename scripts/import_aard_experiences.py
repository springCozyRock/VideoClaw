#!/usr/bin/env python3
"""Import recorded, verified repair pairs; never fabricate prior MAPO examples."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys


def import_run(run, repository):
    from memory.harness.optimization.semantic import ExperienceRepository
    from memory.assets.files import digest, verify_media

    checkpoint = run / "memory/memory.json"
    if json.loads((run / "status.json").read_text())["status"] != "COMPLETED":
        raise ValueError("Only completed source runs may seed later experiments")
    state = json.loads(checkpoint.read_text())
    result = []
    repo = ExperienceRepository(repository)
    for entry in state.get("prompt_experiences", []):
        op = entry["id"]
        prefix, number = op.rsplit("/", 1)
        if not number.isdigit() or int(number) < 1:
            raise ValueError("Cannot locate consecutive source candidates")
        before = state["candidates"][prefix + "/" + str(int(number) - 1)]
        after = state["candidates"][op]
        for key, actual in [
            ("original_prompt", before["prompt"]),
            ("refined_prompt", after["prompt"]),
            ("before", before["review"]),
            ("after", after["review"]),
        ]:
            if entry[key] != actual:
                raise ValueError(
                    "Experience differs from original candidate receipts: " + key
                )
        verify_media(before["media"])
        verify_media(after["media"])
        case = copy.deepcopy(entry)
        case["source"] = {
            "run_fingerprint": state["fingerprint"],
            "story_fingerprint": digest(state["inputs"]["segments"]),
            "before_media": before["media"],
            "after_media": after["media"],
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "implementation": state["inputs"]["implementation"],
            "operation": op,
        }
        result.append(repo.add(case))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, action="append", required=True)
    p.add_argument("--repository", type=Path, required=True)
    p.add_argument(
        "--memory-source", type=Path, default=Path(__file__).resolve().parents[1]
    )
    a = p.parse_args()
    sys.path.insert(0, str(a.memory_source.resolve()))
    for run in a.run:
        print(
            json.dumps(
                {
                    "source": str(run.resolve()),
                    "imported_ids": import_run(run.resolve(), a.repository.resolve()),
                }
            )
        )


if __name__ == "__main__":
    main()
