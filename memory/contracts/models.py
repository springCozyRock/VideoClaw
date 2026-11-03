"""Public contracts. Plans are never observations or completed events."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Segment:
    id: str
    context: str
    duration: float
    entities: tuple = ()
    locations: tuple = ()
    seed_frame: str = ""

    def __post_init__(self):
        if (
            not self.id
            or not self.context
            or not math.isfinite(self.duration)
            or self.duration <= 0
        ):
            raise ValueError(
                "Segment requires an id, context and positive finite duration"
            )


@dataclass(frozen=True)
class Reference:
    id: str
    path: str
    description: str
    entities: tuple = ()
    locations: tuple = ()


FRAME_METRICS = (
    "entity_consistency",
    "environment_consistency",
    "spatial_logic",
    "entity_state",
    "environment_state",
    "instruction_following",
    "physical_plausibility",
)
VIDEO_METRICS = (
    "entity_consistency",
    "environment_consistency",
    "motion_continuity",
    "camera_continuity",
    "intra_entity_consistency",
    "intra_environment_consistency",
    "instruction_following",
    "physical_plausibility",
    "narrative_progression",
)


def strings(value, name):
    if not isinstance(value, list) or any(
        not isinstance(x, str) or not x.strip() for x in value
    ):
        raise ValueError(name + " must be a list of nonempty strings")
    return value


def validate_observation(value, duration):
    if not isinstance(value, dict):
        raise ValueError("Observation must be an object")
    for key in ("entities", "spatial_relations", "events"):
        if not isinstance(value.get(key), list):
            raise ValueError("Observation requires list: " + key)
    if not isinstance(value.get("camera"), str) or not value["camera"].strip():
        raise ValueError(
            "Observation requires camera description (or explicit unknown)"
        )
    ids = set()
    for entity in value["entities"]:
        for key in ("id", "kind", "identity", "state", "motion"):
            if not isinstance(entity.get(key), str) or not entity[key].strip():
                raise ValueError("Entity requires " + key)
        if entity["id"] in ids or entity["kind"] not in (
            "character",
            "object",
            "environment",
        ):
            raise ValueError("Duplicate entity id or invalid kind")
        ids.add(entity["id"])
        if not entity.get("evidence"):
            raise ValueError("Entity requires timed visual evidence")
        for evidence in entity["evidence"]:
            _evidence(evidence, duration)
    for event in value["events"]:
        _evidence(event, duration)
    for rel in value["spatial_relations"]:
        if not all(
            isinstance(rel.get(k), str) and rel[k]
            for k in ("subject", "relation", "object")
        ):
            raise ValueError("Malformed spatial relation")
        if rel["subject"] not in ids or rel["object"] not in ids:
            raise ValueError(
                "Spatial relation references an unobserved entity: "
                + repr({k: rel[k] for k in ("subject", "object") if rel[k] not in ids})
                + "; available exact entity IDs: "
                + repr(sorted(ids))
                + ". Use an existing exact ID, or add the visibly observed entity with timed evidence. "
                "Remove unsupported relations; never invent an entity to satisfy this schema."
            )
    return value


def _evidence(value, duration):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("detail"), str)
        or not value["detail"].strip()
    ):
        raise ValueError("Evidence requires detail")
    start, end = value.get("start"), value.get("end")
    if any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end)):
        raise ValueError("Evidence requires numeric timestamps")
    if not 0 <= start <= end <= duration:
        raise ValueError("Evidence timestamps outside media duration")


def validate_review(value, kind, goals):
    metrics = FRAME_METRICS if kind == "frame" else VIDEO_METRICS
    if not isinstance(value, dict) or set(value.get("scores", {})) != set(metrics):
        raise ValueError("Missing or unexpected review metrics")
    for score in value["scores"].values():
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or not 1 <= score <= 10
        ):
            raise ValueError("Review scores must be finite numbers in [1, 10]")
    for key in ("issues", "hard_failures"):
        strings(value.get(key), key)
    statuses = value.get("goals")
    expected = goals if kind == "video" else []
    if not isinstance(statuses, list) or len(statuses) != len(expected):
        raise ValueError("Review must cover every expected goal")
    for entry, goal in zip(statuses, expected):
        if entry.get("goal") != goal or entry.get("status") not in (
            "completed",
            "unmet",
            "uncertain",
        ):
            raise ValueError("Invalid goal assessment")
        if not isinstance(entry.get("evidence"), str) or not entry["evidence"].strip():
            raise ValueError(
                "Goal assessment requires evidence or uncertainty explanation"
            )
    return value


def accepted(review, policy):
    return (
        not review["hard_failures"]
        and min(review["scores"].values()) >= policy.min_score
        and all(g["status"] == "completed" for g in review["goals"])
    )


def average(review):
    return sum(review["scores"].values()) / len(review["scores"])
