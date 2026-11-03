"""Translate native session artifacts into Memory contracts."""
from pathlib import Path
from memory.contracts.models import Segment, Reference

def convert(agent, data):
    artifacts = agent._session_artifacts(data)
    characters = artifacts.get("character_design", {})
    scenes = {
        s["id"]: s for s in artifacts.get("reference_generation", {}).get("scenes", [])
    }
    style = agent._get_style_prompt(data.get("style", "realistic"))
    segments = []
    for episode in artifacts.get("storyboard", {}).get("episodes", []):
        for item in episode.get("segments", []):
            seed = scenes.get(item["segment_id"], {}).get("selected", "")
            segments.append(
                Segment(
                    item["segment_id"],
                    agent._assemble_prompt(item, style, characters),
                    float(item.get("total_duration", 10)),
                    tuple(item.get("characters") or []),
                    (item["location"],) if item.get("location") else (),
                    str(Path(seed).resolve()) if seed else "",
                )
            )
    references = []
    for group in ("characters", "settings"):
        for item in characters.get(group, []):
            if item.get("selected"):
                name = str(item.get("name") or item.get("id"))
                references.append(
                    Reference(
                        group + "/" + str(item["id"]),
                        str(Path(item["selected"]).resolve()),
                        item.get("description", ""),
                        (name,) if group == "characters" else (),
                        (name,) if group == "settings" else (),
                    )
                )
    return segments, references

