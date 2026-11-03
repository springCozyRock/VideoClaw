"""Validate planner decisions and repair prompts before use."""

from memory.contracts.models import strings


def validate_decision(value, has_previous):
    if not isinstance(value, dict) or type(value.get("continuous")) is not bool:
        raise ValueError("Preparation requires explicit continuity decision")
    if value["continuous"] and not has_previous:
        raise ValueError("First segment cannot continue a previous segment")
    for key in ("continuity_reason", "frame_prompt", "video_prompt"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError("Preparation requires " + key)
    for key in ("goals", "allowed_changes"):
        strings(value.get(key), key)
    if not value["goals"] or len(set(value["goals"])) != len(value["goals"]):
        raise ValueError("Require nonempty unique segment goals")
    return value


def validate_prompt(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Refinement must return a nonempty prompt")
    return value
