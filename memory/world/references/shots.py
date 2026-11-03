"""Extract real shot-end candidates for non-adjacent narrative resumption."""

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from memory.assets.files import media


def extract_shot_ends(path, directory, threshold=0.3, max_shots=16):
    path = Path(path).resolve(strict=True)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            text=True,
        )
    )
    stream = probe["streams"][0]
    rate = float(Fraction(stream["avg_frame_rate"]))
    duration = float(stream.get("duration", probe["format"]["duration"]))
    if rate <= 0 or duration <= 0 or not 0 < threshold < 1 or max_shots < 1:
        raise ValueError("Invalid video/detector configuration")
    detected = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-v",
            "info",
            "-i",
            str(path),
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    cuts = sorted(
        {
            float(x)
            for x in re.findall(r"pts_time:([0-9.]+)", detected.stderr)
            if 1 / rate < float(x) < duration - 1 / rate
        }
    )
    boundaries = cuts + [duration]
    # Never label arbitrary sampled frames as shot ends. If capped, retain an
    # evenly distributed subset of the actual detected shot ends including last.
    selected = list(range(len(boundaries)))
    if len(selected) > max_shots:
        selected = sorted(
            {
                round(i * (len(boundaries) - 1) / max(1, max_shots - 1))
                for i in range(max_shots)
            }
        )
        if max_shots == 1:
            selected = [len(boundaries) - 1]
    candidates = []
    for i in selected:
        start = boundaries[i - 1] if i else 0
        end = boundaries[i]
        timestamp = max(start, end - 1 / rate)
        target = directory / f"shot-{i:03d}-end.png"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-ss",
                str(timestamp),
                "-i",
                str(path),
                "-frames:v",
                "1",
                str(target),
            ],
            check=True,
        )
        candidates.append(
            {
                "id": f"shot-{i:03d}",
                "start": start,
                "end": end,
                "frame_time": timestamp,
                "media": media(target),
            }
        )
    return {
        "source_video": media(path),
        "duration": duration,
        "detector": {
            "method": "ffmpeg_scene_score",
            "threshold": threshold,
            "max_shots": max_shots,
            "limitation": "Heuristic cuts may miss dissolves or over-detect abrupt motion",
        },
        "detected_cut_times": cuts,
        "candidates": candidates,
    }


def validate_selection(value, candidates):
    if value.get("shot_id") not in {c["id"] for c in candidates}:
        raise ValueError(
            "Historical boundary must be one of the actual extracted shot ends"
        )
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise ValueError("Historical boundary selection needs a reason")
    return value
