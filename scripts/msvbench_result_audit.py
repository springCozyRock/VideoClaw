"""Classify execution and coverage without changing native MSVBench scores."""
import math
import re


def _errors(value, path=()):
    if isinstance(value, float) and not math.isfinite(value):
        yield {"path": list(path), "message": "non-finite native value"}
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("error", "traceback") and item:
                yield {"path": list(path + (key,)), "message": str(item)}
            elif key == 'detailed_results' and isinstance(item, dict):
                for name, detail in item.items():
                    if detail is None:
                        yield {'path': list(path + (key, name)), 'message': 'Native detailed analysis is missing'}
                    else:
                        yield from _errors(detail, path + (key, name))
            elif isinstance(item, (dict, list, float)):
                yield from _errors(item, path + (key,))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _errors(item, path + (i,))


def _summaries(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "summary" and isinstance(item, dict):
                yield {"path": list(path + (key,)), "values": item}
            elif isinstance(item, (dict, list)):
                yield from _summaries(item, path + (key,))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _summaries(item, path + (i,))


def audit_result(native_result, log, script=None, transport_errors=(), exception=None):
    """Return diagnostics; retain all native score/aggregation fields verbatim."""
    clips = [clip for scene in (script or {}).get("script", [])
             for clip in scene.get("clips", [])]
    empty = {i for i, clip in enumerate(clips, 1) if not clip.get("characters")}
    issues = list(_errors(native_result))
    warnings = []
    mapping = re.compile(r"^\s*(\d+): No character mapping found\s*$")
    for line in log.splitlines():
        match = mapping.match(line)
        if match:
            item = {"path": ["log"], "message": line.strip(),
                    "official_shot_index": int(match[1])}
            if int(match[1]) in empty:
                item["reason"] = "Official character annotation is empty; native skip retained"
                warnings.append(item)
            else:
                issues.append(item)
        elif re.match(r"^\s*(Error\b|❌|Failed to parse|Failed to load|Failed to initialize|Warning: Could not parse)", line):
            issues.append({"path": ["log"], "message": line.strip()})
    fatal = []
    if exception:
        fatal.append({"path": ["execution"], "message": str(exception)})
    for error in transport_errors:
        fatal.append({"path": ["transport"], "message": str(error)})
    summaries = list(_summaries(native_result))
    has_summary_score = any(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value)
        and not any(term in key.lower() for term in ("count", "total_", "duration", "comparisons", "pairs_found"))
        for item in summaries for key, value in item["values"].items()
    )
    comparison_counts = [value for item in summaries for key, value in item['values'].items()
                         if 'comparisons' in key.lower() and isinstance(value, (int, float))]
    if comparison_counts and not any(value > 0 for value in comparison_counts):
        has_summary_score = False
    def missing_all_details(value):
        if isinstance(value, dict):
            details = value.get('detailed_results')
            if isinstance(details, dict) and details and all(x is None for x in details.values()):
                return True
            return any(missing_all_details(x) for x in value.values())
        if isinstance(value, list):
            return any(missing_all_details(x) for x in value)
        return False
    if missing_all_details(native_result):
        has_summary_score = False
    status = "FAILED" if fatal or (issues and not has_summary_score) else "PARTIAL" if issues else "SCORED"
    return {
        "status": status,
        "execution_status": "ERROR" if fatal else "COMPLETED",
        "score_status": "UNAVAILABLE" if status == "FAILED" else "PARTIAL" if issues else "AVAILABLE",
        "issues": fatal + issues,
        "warnings": warnings,
        "coverage": {
            "official_shots": len(clips) if script is not None else None,
            "official_empty_character_shots": sorted(empty),
            "native_summaries": summaries,
            "failed_or_skipped_comparisons": len(issues),
            "note": "Counts describe native diagnostics, not a normalized coverage percentage. Native aggregation is unchanged."
        }
    }
