"""Execution gates for observed narrative prerequisites."""
from memory.assets.files import digest

def check_event_dependencies(plan, segment, records):
    from memory.contracts.errors import QualityBlocked
    beats = {b["segment_id"]: b for b in (plan or {}).get("beats", [])}
    actual = {r["segment"]["id"]: r for r in records}
    for sid in beats.get(segment.id, {}).get("depends_on", []):
        evidence = actual.get(sid, {}).get("event_assessment") or {}
        if evidence.get("status") != "pass" or digest(evidence.get("beat")) != digest(beats.get(sid)):
            raise QualityBlocked("Unverified event prerequisite: " + sid + " -> " + segment.id)

