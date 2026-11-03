#!/usr/bin/env python3
"""Validate evaluation_manifest.json for lvm-action-wan3 deliveries.

Checks the structural and content rules that the evaluation contract requires:
shot ordering and ids, integer durations summing to the target duration, real
source segment paths (never final.mp4), contiguous scene coverage, declared
characters with valid tags, and per-shot character keys. When --plan is given,
the manifest is cross-checked against the adopted segments of plan.json.

Usage:
  python validate_manifest.py --manifest /abs/evaluation_manifest.json
  python validate_manifest.py --manifest /abs/evaluation_manifest.json \
      --plan /abs/plan.json [--allow-missing-files] [--json-summary out.json]

Exit code 0 means no ERROR was found (warnings may still be printed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

VALID_TAGS = ("realistic_human", "unrealistic_human", "non_human")
FINAL_VIDEO_NAMES = ("final.mp4", "final.mov", "final.mkv", "final.webm")


class Report:
    """Collects de-duplicated errors and warnings in discovery order."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._seen: set[str] = set()

    def error(self, msg: str) -> None:
        if ("E", msg) in self._seen:
            return
        self._seen.add(("E", msg))
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        if ("W", msg) in self._seen:
            return
        self._seen.add(("W", msg))
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_json(path: str, report: Report, label: str):
    p = Path(path)
    if not p.exists():
        report.error(f"{label}: file not found: {p}")
        return None
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        report.error(f"{label}: invalid JSON ({exc})")
        return None
    if not isinstance(data, dict):
        report.error(f"{label}: top level must be a JSON object")
        return None
    return data


def as_int(value, field: str, report: Report, allow_float_coercion: bool = True):
    """Return an int or None, reporting a type problem."""
    if isinstance(value, bool):
        report.error(f"{field}: must be an integer, got boolean")
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and allow_float_coercion:
        if float(value).is_integer():
            report.warn(f"{field}: {value!r} is a float; write it as an integer")
            return int(value)
        report.error(f"{field}: must be an integer, got non-integral float {value!r}")
        return None
    report.error(f"{field}: must be an integer, got {type(value).__name__}")
    return None


def as_nonempty_str(value, field: str, report: Report):
    if not isinstance(value, str) or not value.strip():
        report.error(f"{field}: must be a non-empty string")
        return None
    return value.strip()


def validate_manifest(manifest: dict, args, report: Report) -> None:
    manifest_path = Path(args.manifest).resolve()

    # --- top level keys -------------------------------------------------
    for key in ("duration_sec", "bible", "shots", "scenes", "characters"):
        if key not in manifest:
            report.error(f"manifest: missing required top-level key '{key}'")
    if report.errors:
        return

    total = as_int(manifest.get("duration_sec"), "duration_sec", report)
    if total is not None and total <= 0:
        report.error(f"duration_sec: must be a positive integer, got {total}")

    bible = as_nonempty_str(manifest.get("bible"), "bible", report)
    if bible is not None and len(bible) < 20:
        report.warn("bible: summary looks too short to describe unified settings")

    if args.target_duration is not None:
        if total is not None and total != args.target_duration:
            report.error(
                f"duration_sec: {total} does not match the requested target duration "
                f"{args.target_duration}"
            )

    shots = manifest.get("shots")
    scenes = manifest.get("scenes")
    characters = manifest.get("characters")
    if not isinstance(shots, list):
        report.error("shots: must be a list")
        return
    if not isinstance(scenes, list):
        report.error("scenes: must be a list")
        scenes = None
    if not isinstance(characters, list):
        report.error("characters: must be a list (use [] only for tasks without people)")
        characters = None

    char_keys = validate_characters(characters, report)
    validate_shots(shots, char_keys, manifest_path, args, report, total)
    if scenes is not None:
        validate_scenes(scenes, report, total)


def validate_characters(characters, report: Report):
    if characters is None:
        return set()
    keys: set[str] = set()
    if not characters:
        report.warn(
            "characters: empty. Only allowed when the task truly has no people; "
            "never hide an expected character by declaring a people-less task"
        )
        return keys
    seen_first: set[int] = set()
    for idx, ch in enumerate(characters):
        where = f"characters[{idx}]"
        if not isinstance(ch, dict):
            report.error(f"{where}: must be an object")
            continue
        key = as_nonempty_str(ch.get("key"), f"{where}.key", report)
        if key is not None:
            if key in keys:
                report.error(f"{where}.key: duplicate character key '{key}'")
            keys.add(key)
        as_nonempty_str(ch.get("name"), f"{where}.name", report)
        prompt_en = as_nonempty_str(ch.get("prompt_en"), f"{where}.prompt_en", report)
        if prompt_en is not None and len(prompt_en.split()) < 2:
            report.warn(
                f"{where}.prompt_en: '{prompt_en}' is too vague to locate the character; "
                "use a distinguishing English appearance phrase"
            )
        tag = ch.get("tag")
        if tag not in VALID_TAGS:
            report.error(
                f"{where}.tag: must be one of {', '.join(VALID_TAGS)}; got {tag!r}"
            )
        first = as_int(ch.get("first_shot_id"), f"{where}.first_shot_id", report)
        if first is not None:
            if first < 1:
                report.error(f"{where}.first_shot_id: must be >= 1, got {first}")
            seen_first.add(first)
        extra = set(ch.keys()) - {"key", "name", "prompt_en", "tag", "first_shot_id"}
        if extra:
            report.warn(f"{where}: unexpected extra fields {sorted(extra)}")
    return keys


def validate_shots(shots, char_keys, manifest_path: Path, args, report: Report, total):
    if not shots:
        report.error("shots: must contain at least one shot")
        return
    duration_sum = 0
    seen_sources: dict[str, int] = {}
    for idx, shot in enumerate(shots):
        where = f"shots[{idx}]"
        if not isinstance(shot, dict):
            report.error(f"{where}: must be an object")
            continue
        expected_id = idx + 1
        sid = as_int(shot.get("shot_id"), f"{where}.shot_id", report)
        if sid is not None and sid != expected_id:
            report.error(
                f"{where}.shot_id: must be consecutive from 1 in merge order; "
                f"expected {expected_id}, got {sid}"
            )
        dur = as_int(shot.get("duration_sec"), f"{where}.duration_sec", report)
        if dur is not None:
            if dur <= 0:
                report.error(f"{where}.duration_sec: must be a positive integer, got {dur}")
            else:
                duration_sum += dur
        desc = as_nonempty_str(shot.get("description"), f"{where}.description", report)
        if desc is not None and len(desc) < 8:
            report.warn(f"{where}.description: looks too short to describe the segment")

        src = shot.get("source_video_path")
        src = as_nonempty_str(src, f"{where}.source_video_path", report)
        if src is not None:
            sp = Path(src)
            if sp.name in FINAL_VIDEO_NAMES:
                report.error(
                    f"{where}.source_video_path: must point to the original generated "
                    f"segment, not the merged output '{sp.name}'"
                )
            if not sp.is_absolute():
                report.error(
                    f"{where}.source_video_path: must be an absolute path, got '{src}'"
                )
            elif sp.resolve() == manifest_path:
                report.error(f"{where}.source_video_path: points at the manifest itself")
            elif not args.allow_missing_files and not sp.exists():
                report.error(f"{where}.source_video_path: file does not exist: {sp}")
            key = str(sp)
            if key in seen_sources:
                report.warn(
                    f"{where}.source_video_path: same source file used by shot "
                    f"{seen_sources[key]} and shot {sid if sid is not None else expected_id}; "
                    "confirm this is a genuine reuse and not padding"
                )
            else:
                seen_sources[key] = sid if sid is not None else expected_id

        start = shot.get("source_start_sec")
        start_i = as_int(start, f"{where}.source_start_sec", report)
        if start_i is not None and start_i != 0:
            report.error(
                f"{where}.source_start_sec: merge-video uses each input from its start, "
                f"so this must be 0; got {start_i}. If the segment was trimmed, save the "
                "trimmed file separately and reference that file with start 0"
            )

        ckeys = shot.get("character_keys")
        if ckeys is None:
            report.warn(f"{where}.character_keys: missing; use [] when no character appears")
        elif not isinstance(ckeys, list):
            report.error(f"{where}.character_keys: must be a list")
        else:
            for ck in ckeys:
                if not isinstance(ck, str) or not ck.strip():
                    report.error(f"{where}.character_keys: entries must be non-empty strings")
                elif char_keys and ck not in char_keys:
                    report.error(
                        f"{where}.character_keys: '{ck}' is not declared in characters"
                    )
        extra = set(shot.keys()) - {
            "shot_id",
            "duration_sec",
            "description",
            "source_video_path",
            "source_start_sec",
            "character_keys",
        }
        if extra:
            report.warn(f"{where}: unexpected extra fields {sorted(extra)}")

    if total is not None and duration_sum != total:
        report.error(
            f"shots: duration_sec sum {duration_sum} != duration_sec {total}; "
            "the sum must equal the target duration"
        )
    if args.allow_missing_files:
        report.warn("shots: file existence was not checked because --allow-missing-files was set")


def validate_scenes(scenes, report: Report, total):
    if not scenes:
        report.error("scenes: must contain at least one scene covering the whole video")
        return
    prev_end = 0
    for idx, sc in enumerate(scenes):
        where = f"scenes[{idx}]"
        if not isinstance(sc, dict):
            report.error(f"{where}: must be an object")
            continue
        expected_id = idx + 1
        sid = as_int(sc.get("scene_id"), f"{where}.scene_id", report)
        if sid is not None and sid != expected_id:
            report.error(
                f"{where}.scene_id: must be consecutive from 1; expected {expected_id}, got {sid}"
            )
        start = as_int(sc.get("start_sec"), f"{where}.start_sec", report)
        end = as_int(sc.get("end_sec"), f"{where}.end_sec", report)
        as_nonempty_str(sc.get("description"), f"{where}.description", report)
        if start is None or end is None:
            continue
        if start != prev_end:
            report.error(
                f"{where}: start_sec {start} must equal previous end_sec {prev_end} "
                "(scenes must cover the video contiguously without gaps or overlap)"
            )
        if end <= start:
            report.error(f"{where}: end_sec {end} must be greater than start_sec {start}")
        prev_end = end
    if total is not None and prev_end != total:
        report.error(
            f"scenes: last end_sec {prev_end} != duration_sec {total}; "
            "scenes must cover the full video"
        )


def validate_plan_crosscheck(plan: dict, manifest: dict, args, report: Report) -> None:
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        report.warn("plan.segments: missing or empty; cannot cross-check the manifest")
        return

    adopted: list[dict] = []
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            report.error(f"plan.segments[{idx}]: must be an object")
            continue
        status = str(seg.get("status", "")).strip().lower()
        if status == "adopted":
            adopted.append(seg)
        elif status in {"planned", "generated", "qc_pass", "qc_fail", "regenerated"}:
            report.warn(
                f"plan.segments[{idx}] (segment_id={seg.get('segment_id')}): status "
                f"'{status}' is not final; mark it adopted or discarded before delivery"
            )
    if not adopted:
        report.error("plan.segments: no segment has status 'adopted'")
        return

    adopted_paths = []
    for seg in adopted:
        p = seg.get("adopted_path")
        if not isinstance(p, str) or not p.strip():
            report.error(
                f"plan.segments (segment_id={seg.get('segment_id')}): status is adopted "
                "but adopted_path is missing"
            )
            continue
        adopted_paths.append(str(Path(p.strip()).resolve()))

    shots = manifest.get("shots") if isinstance(manifest.get("shots"), list) else []
    manifest_paths = []
    for shot in shots:
        if isinstance(shot, dict) and isinstance(shot.get("source_video_path"), str):
            manifest_paths.append(str(Path(shot["source_video_path"].strip()).resolve()))

    if len(adopted_paths) != len(manifest_paths):
        report.error(
            f"plan/manifest mismatch: {len(adopted_paths)} adopted segments in plan.json "
            f"but {len(manifest_paths)} shots in the manifest"
        )
    for i, (a, m) in enumerate(zip(adopted_paths, manifest_paths)):
        if a != m:
            report.error(
                f"plan/manifest mismatch at position {i + 1}: plan adopted_path {a} "
                f"!= manifest source_video_path {m}"
            )

    merge_order = plan.get("merge_order")
    if isinstance(merge_order, list) and merge_order:
        order_paths = [str(Path(str(x).strip()).resolve()) for x in merge_order]
        if order_paths != manifest_paths:
            report.error(
                "plan.merge_order does not match the manifest shot order; the manifest "
                "must reflect the real merge order"
            )
    else:
        report.warn("plan.merge_order: missing or empty; record the real merge --input order")

    task = plan.get("task") if isinstance(plan.get("task"), dict) else {}
    target = task.get("target_duration_sec")
    if target is not None:
        t = as_int(target, "plan.task.target_duration_sec", report)
        m = manifest.get("duration_sec")
        m_i = as_int(m, "manifest.duration_sec", report)
        if t is not None and m_i is not None and t != m_i:
            report.error(
                f"plan/manifest mismatch: target_duration_sec {t} != manifest duration_sec {m_i}"
            )
    else:
        report.warn("plan.task.target_duration_sec: missing")

    budget = plan.get("duration_budget")
    if isinstance(budget, dict):
        planned = budget.get("planned_sum_sec")
        if planned is not None:
            p_i = as_int(planned, "plan.duration_budget.planned_sum_sec", report)
            m_i = as_int(manifest.get("duration_sec"), "manifest.duration_sec", report)
            if p_i is not None and m_i is not None and p_i != m_i:
                report.error(
                    f"plan.duration_budget.planned_sum_sec {p_i} != manifest duration_sec {m_i}; "
                    "planned segment durations must sum exactly to the target duration"
                )
    else:
        report.warn("plan.duration_budget: missing; record target, planned and adopted sums")

    plan_char_keys: set[str] = set()
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        for ck in seg.get("characters") or []:
            if isinstance(ck, str) and ck.strip():
                plan_char_keys.add(ck.strip())
    manifest_keys = set()
    for ch in manifest.get("characters") or []:
        if isinstance(ch, dict) and isinstance(ch.get("key"), str):
            manifest_keys.add(ch["key"].strip())
    missing = sorted(plan_char_keys - manifest_keys)
    if missing:
        report.error(
            f"plan/manifest mismatch: characters used by planned segments are missing "
            f"from manifest.characters: {missing}"
        )
    unused = sorted(manifest_keys - plan_char_keys)
    if unused:
        report.warn(
            f"manifest.characters declares keys never used by any planned segment: {unused}"
        )

    if not args.allow_missing_files:
        for seg in adopted:
            p = seg.get("adopted_path")
            if isinstance(p, str) and p.strip() and not Path(p.strip()).exists():
                report.error(
                    f"plan.segments (segment_id={seg.get('segment_id')}): adopted_path "
                    f"does not exist: {p}"
                )
            attempts = seg.get("attempts")
            if not isinstance(attempts, list) or not attempts:
                report.warn(
                    f"plan.segments (segment_id={seg.get('segment_id')}): no attempts recorded; "
                    "keep attempt history for cost and regeneration traceability"
                )
            if not seg.get("prompt"):
                report.warn(
                    f"plan.segments (segment_id={seg.get('segment_id')}): prompt not recorded"
                )
            if seg.get("seed") is None:
                report.warn(
                    f"plan.segments (segment_id={seg.get('segment_id')}): seed not recorded"
                )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate evaluation_manifest.json (and optionally plan.json)."
    )
    parser.add_argument("--manifest", required=True, help="path to evaluation_manifest.json")
    parser.add_argument("--plan", help="optional path to plan.json for cross-checking")
    parser.add_argument(
        "--target-duration",
        type=int,
        help="optional requested total duration in seconds to verify duration_sec against",
    )
    parser.add_argument(
        "--allow-missing-files",
        action="store_true",
        help="skip media file existence checks (schema-only validation)",
    )
    parser.add_argument(
        "--json-summary",
        help="optional path to write a machine-readable summary of errors and warnings",
    )
    args = parser.parse_args(argv)

    report = Report()
    manifest = load_json(args.manifest, report, "manifest")
    if manifest is not None:
        validate_manifest(manifest, args, report)

    plan = None
    if args.plan and manifest is not None:
        plan = load_json(args.plan, report, "plan")
        if plan is not None:
            validate_plan_crosscheck(plan, manifest, args, report)
    elif args.plan and manifest is None:
        report.warn("plan cross-check skipped because the manifest could not be loaded")

    for msg in report.errors:
        print(f"ERROR: {msg}")
    for msg in report.warnings:
        print(f"WARN: {msg}")
    print(
        f"RESULT: {'FAIL' if not report.ok else 'PASS'} "
        f"({len(report.errors)} error(s), {len(report.warnings)} warning(s)) "
        f"for {os.path.abspath(args.manifest)}"
    )

    if args.json_summary:
        summary = {
            "manifest": os.path.abspath(args.manifest),
            "plan": os.path.abspath(args.plan) if args.plan else None,
            "ok": report.ok,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "errors": report.errors,
            "warnings": report.warnings,
        }
        Path(args.json_summary).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"SUMMARY_WRITTEN: {os.path.abspath(args.json_summary)}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
