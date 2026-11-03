"""Story-level reference DAG; planned assets never become observed video facts."""

from dataclasses import asdict
from memory.contracts.models import Reference, Segment
from memory.assets.files import media, verify_media


def validate_plan(value, sources, max_extra=4, max_dependencies=8):
    nodes = value.get("nodes")
    if (
        not isinstance(nodes, list)
        or (not nodes and bool(sources))
        or len(nodes) > len(sources) + max_extra
    ):
        raise ValueError(
            "Reference plan must contain existing anchors and at most four extra assets"
        )
    existing = {s["id"]: s for s in sources}
    by_id = {}
    for node in nodes:
        name = node.get("id")
        if not isinstance(name, str) or not name or name in by_id:
            raise ValueError("Reference ids must be unique nonempty strings")
        by_id[name] = node
        if node.get("action") not in ("reuse", "generate"):
            raise ValueError("Reference action must be reuse or generate")
        if node["action"] == "reuse" and name not in existing:
            raise ValueError("Cannot reuse an unknown asset")
        # Supplied character identity anchors are immutable. Style changes belong
        # in environments or explicitly planned future state references.
        if (
            name in existing
            and existing[name]["entities"]
            and node["action"] != "reuse"
        ):
            raise ValueError("Supplied character anchors must be reused unchanged")
        for field in ("description", "prompt", "reason"):
            if not isinstance(node.get(field), str) or not node[field].strip():
                raise ValueError("Reference node requires " + field)
        for field in ("entities", "locations", "depends_on"):
            if not isinstance(node.get(field), list) or any(
                not isinstance(v, str) or not v for v in node[field]
            ):
                raise ValueError("Reference node requires string list " + field)
        if len(node["depends_on"]) > max_dependencies or len(
            set(node["depends_on"])
        ) != len(node["depends_on"]):
            raise ValueError("Duplicate or excessive dependencies")
        if node["action"] == "reuse" and node["depends_on"]:
            raise ValueError("Existing anchor has no generation dependencies")
    if not set(existing) <= set(by_id):
        raise ValueError("Reference planner omitted supplied anchors")
    for node in nodes:
        if not set(node["depends_on"]) <= set(by_id):
            raise ValueError("Unknown reference dependency")
    # Stable topological ordering, including cycle detection.
    order, remaining = [], list(by_id)
    while remaining:
        ready = [n for n in remaining if set(by_id[n]["depends_on"]) <= set(order)]
        if not ready:
            raise ValueError("Cyclic reference dependency")
        order.extend(ready)
        remaining = [n for n in remaining if n not in ready]
    return dict(value, nodes=nodes, topological_order=order)


def components(plan):
    adjacency = {n["id"]: set(n["depends_on"]) for n in plan["nodes"]}
    for node, deps in list(adjacency.items()):
        for dep in list(deps):
            adjacency[dep].add(node)
    groups, seen = [], set()
    for start in plan["topological_order"]:
        if start in seen:
            continue
        group, todo = [], [start]
        while todo:
            node = todo.pop()
            if node in seen:
                continue
            seen.add(node)
            group.append(node)
            todo.extend(sorted(adjacency[node] - seen, reverse=True))
        groups.append(group)
    return groups


def initialize(store, backend, segments, sources, max_references, cancel=None):
    request = {
        "storyline": [asdict(s) for s in segments],
        "sources": sources,
        "max_extra_assets": 4,
        "max_dependencies": max_references,
        "semantics": "Reference designs are planned anchors, never observed completed events.",
    }
    plan = store.operation(
        "global_references/plan",
        request,
        lambda: validate_plan(
            backend.plan_global_references(request),
            sources,
            max_dependencies=max_references,
        ),
    )
    validate_plan(plan, sources, max_dependencies=max_references)
    source_by_id = {s["id"]: s for s in sources}
    by_id = {n["id"]: n for n in plan["nodes"]}
    resolved = {}
    for index, name in enumerate(plan["topological_order"]):
        if cancel:
            cancel()
        node = by_id[name]
        if node["action"] == "reuse":
            resolved[name] = source_by_id[name]
            verify_media(resolved[name]["media"])
            continue
        dependencies = [resolved[d]["media"] for d in node["depends_on"]]
        for asset in dependencies:
            verify_media(asset)
        target = store.directory / "global_references" / ("asset-%03d.png" % index)
        target.parent.mkdir(parents=True, exist_ok=True)
        segment = Segment(
            "reference/" + name,
            node["description"],
            1,
            tuple(node["entities"]),
            tuple(node["locations"]),
        )
        asset = store.operation(
            "global_references/render/%d" % index,
            {"node": node, "dependencies": dependencies},
            lambda: media(
                backend.render_frame(
                    segment, node["prompt"], [d["path"] for d in dependencies], target
                )
            ),
        )
        verify_media(asset)
        resolved[name] = dict(
            asdict(
                Reference(
                    name,
                    asset["path"],
                    node["description"],
                    tuple(node["entities"]),
                    tuple(node["locations"]),
                )
            ),
            media=asset,
        )
    store.data["global_reference_graph"] = dict(
        plan,
        weak_components=components(plan),
        resolved=list(resolved.values()),
        evidence_type="planned_reference_assets",
    )
    store.save()
    return list(resolved.values())
