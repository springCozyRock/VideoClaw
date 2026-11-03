"""Select observed history and reference images for current and next segments."""

from dataclasses import asdict


class ContextRetrieval:
    def __init__(self, store, backend, policy):
        self.store, self.backend, self.policy = store, backend, policy

    def index(self, segment, records, ledger):
        related = set(segment.entities) | set(segment.locations)
        important = {
            row["latest"]["segment_id"]
            for row in ledger.values()
            if row["entity"] in related
        }
        ranked = sorted(
            records,
            key=lambda r: (
                r["segment"]["id"] in important,
                len(
                    related
                    & (set(r["segment"]["entities"]) | set(r["segment"]["locations"]))
                ),
                r["index"],
            ),
            reverse=True,
        )
        chosen = ranked[: self.policy.max_retrieval_candidates]
        return [
            {
                "id": r["segment"]["id"],
                "context": r["segment"]["context"][:1200],
                "observed": {
                    "entities": [
                        {k: e[k][:320] for k in ("identity", "state", "motion")}
                        for e in r["observation"]["entities"][:12]
                    ],
                    "events": r["observation"].get("events", [])[:8],
                },
                "state_observation": r.get("state_observation", {}),
                "quality_passed": r["accepted"],
            }
            for r in chosen
        ]

    def retrieve(self, key, segment, records, refs, ledger):
        query = {
            "current": asdict(segment),
            "previous": self.index(segment, records, ledger),
            "references": [
                {
                    "id": r["id"],
                    "description": r["description"],
                    "entities": r["entities"],
                    "locations": r["locations"],
                }
                for r in refs
            ],
            "top_k": self.policy.top_k,
            "max_references": self.policy.max_references,
        }
        choice = self.store.operation(
            key, query, lambda: self.backend.select_context(query)
        )
        ids, ref_ids = choice["segment_ids"], choice["reference_ids"]
        if (
            len(ids) > self.policy.top_k
            or len(ref_ids) > self.policy.max_references
            or not set(ids) <= {r["id"] for r in query["previous"]}
            or not set(ref_ids) <= {r["id"] for r in refs}
        ):
            raise ValueError("Invalid context retrieval")
        keep = set(ids) | ({records[-1]["segment"]["id"]} if records else set())
        return [r for r in records if r["segment"]["id"] in keep], [
            r for r in refs if r["id"] in ref_ids
        ]

    def images(self, context):
        paths = []
        for r in reversed(context["history"]):
            paths.append(r["end"]["path"])
        paths.extend(r["media"]["path"] for r in context["references"])
        return list(dict.fromkeys(paths))[: self.policy.max_references]
