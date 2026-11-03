"""A²RD public memory schema. Plans and generation conditions are not observations."""
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class SegmentMemory:
    segment_id: str
    revision_id: str
    story_revision: str
    T: dict[str, Any]
    F: dict[str, str]
    V: str
    generation: dict[str, Any]
    evaluation: dict[str, Any]
    dependencies: dict[str, str]

    def to_dict(self):
        if not all((self.segment_id, self.revision_id, self.V)):
            raise ValueError("Segment memory needs identity and an actual video")
        if set(self.F) != {"begin", "end"}:
            raise ValueError("F must contain ACTUAL decoded boundaries")
        if not all(k in self.T for k in ("visual_arcs", "spatial_relations", "camera", "events")):
            raise ValueError("Incomplete textual state T")
        return asdict(self)


def textual_state(record):
    observation = record["observation"]
    facts = record.get("state_observation", {}).get("facts", [])
    arcs = []
    for entity in observation.get("entities", []):
        begin = {f["attribute"]: f for f in facts if f["entity"] == entity["id"] and f["phase"] == "begin"}
        end = {f["attribute"]: f for f in facts if f["entity"] == entity["id"] and f["phase"] == "end"}
        changes = [{"attribute": k, "before": begin[k], "after": end[k]} for k in begin.keys() & end.keys()
                   if begin[k]["status"] == end[k]["status"] == "observed" and begin[k]["value"] != end[k]["value"]]
        arcs.append(dict(entity, begin_state=begin, end_state=end, identity_changes=changes))
    return {
        "visual_arcs": arcs,
        "spatial_relations": observation.get("spatial_relations", []),
        "camera": observation.get("camera", "unknown"),
        "events": observation.get("events", []),
        "state_facts": facts,
        "extraction": observation.get("extraction", {}),
    }
