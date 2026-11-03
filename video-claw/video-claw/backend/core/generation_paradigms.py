"""Visual-input production contracts. No model calls or session side effects.

Generation units remain VideoClaw segments, which may contain several shots.
Grid cells are jointly drawn per episode in batches of four, then used as first
frames. keyframe2v draws one independent first frame per segment.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PARADIGMS = ('fflf2v', 'grid2v', 'multiref2v', 'keyframe2v')
ALIASES = {'first_frame': 'keyframe2v', 'start_end_frame': 'fflf2v', 'reference': 'multiref2v'}
MODES = {'fflf2v': 'start_end_frame', 'grid2v': 'first_frame',
         'multiref2v': 'reference', 'keyframe2v': 'first_frame'}
MODEL_KEYS = {'first_frame': 'video_first_frame_model',
              'start_end_frame': 'video_start_end_model', 'reference': 'video_reference_model'}
ABILITIES = {'first_frame': 'first_frame_i2v', 'start_end_frame': 'start_end_frame_i2v',
             'reference': 'reference_to_video'}


def resolve_paradigm(values: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    # Request-level selectors take precedence over the saved selector.
    value = (values.get('generation_paradigm') or values.get('video_generation_mode')
             or meta.get('generation_paradigm') or meta.get('video_generation_mode') or 'keyframe2v')
    value = ALIASES.get(value, value)
    if value not in PARADIGMS:
        raise ValueError(f'Unknown generation paradigm: {value}')
    return value


def validate_model(model: str, mode: str, duration: int | None = None) -> None:
    from models.config_model import parse_api_model, video_capabilities
    provider, model_id = parse_api_model(model, 'video')
    caps = video_capabilities(provider, model_id)
    # Advertised vendor features are insufficient: use implemented adapter features.
    if ABILITIES[mode] not in caps.get('adapter_ability_types', []):
        raise ValueError(f'{model} adapter does not support {mode}; choose a compatible model')
    limit = caps.get('duration') or {}
    if duration is not None and limit.get('verified'):
        if duration < limit.get('min', 0) or duration > limit.get('max', float('inf')):
            raise ValueError(f'{model}: duration {duration}s outside supported range {limit}')


def selected_references(segment: dict, assets: dict) -> list[dict]:
    """Resolve explicitly named entities; missing named props are errors, never omitted."""
    result = []
    for kind, names in (('characters', segment.get('characters') or []),
                        ('settings', [segment['location']] if segment.get('location') else []),
                        ('elements', segment.get('elements') or segment.get('props') or [])):
        candidates = assets.get(kind) or (assets.get('props', []) if kind == 'elements' else [])
        for name in names:
            key = name.get('id') or name.get('name') if isinstance(name, dict) else name
            item = next((x for x in candidates if key in (x.get('id'), x.get('name'))), None)
            if item is None:
                raise ValueError(f"{segment['segment_id']}: missing {kind} asset {key!r}; add/select it before rendering")
            path = item.get('selected')
            if not path or not Path(path).is_file():
                raise ValueError(f"{segment['segment_id']}: missing selected image for {kind} {key!r}")
            if not any(x['path'] == str(Path(path).absolute()) for x in result):
                result.append({'kind': kind, 'id': item.get('id') or str(key),
                               'name': item.get('name') or str(key), 'path': str(Path(path).absolute())})
    return result


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def file_identity(path: str) -> dict:
    p = Path(path)
    return {'path': str(p.absolute()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def grid_groups(episodes: list[dict], size: int = 4) -> list[list[dict]]:
    if not 1 <= size <= 4:
        raise ValueError('grid_group_size must be between 1 and 4')
    groups = []
    for episode in episodes:
        segments = episode.get('segments', [])
        groups.extend(segments[i:i + size] for i in range(0, len(segments), size))
    return groups


def slice_grid(path: str, segments: list[dict], directory: Path) -> list[dict]:
    from PIL import Image
    # Fixed 2x2 layout, even for a partial final group; unused cells stay blank.
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    with Image.open(path) as source:
        source = source.convert('RGB')
        width, height = source.size
        if width < 4 or height < 4:
            raise ValueError('Grid image is too small')
        for i, segment in enumerate(segments):
            col, row = i % 2, i // 2
            box = (col * width // 2, row * height // 2,
                   (col + 1) * width // 2, (row + 1) * height // 2)
            target = directory / f'cell_{i + 1}.png'
            source.crop(box).save(target)
            records.append({'unit_id': segment['segment_id'], 'first_frame': str(target.absolute()),
                            'grid_source': str(Path(path).absolute()), 'grid_cell': i,
                            'grid_box': list(box), 'grid_layout': [2, 2]})
    return records


def conditioning(record: dict, paradigm: str) -> tuple[str | None, str | None, list[str]]:
    if record.get('generation_paradigm') != paradigm:
        raise ValueError('Reference assets belong to another paradigm; rerun reference_generation')
    first, last = record.get('selected') or record.get('first_frame'), record.get('last_frame')
    refs = [r['path'] for r in record.get('references', [])]
    required = refs if paradigm == 'multiref2v' else [first, last] if paradigm == 'fflf2v' else [first]
    if not required or any(not p or not Path(p).is_file() for p in required):
        raise ValueError(f"{record.get('unit_id')}: incomplete {paradigm} inputs; rerun reference_generation")
    return (None, None, refs) if paradigm == 'multiref2v' else (first, last if paradigm == 'fflf2v' else None, [])


def frame_prompt(segment: dict, endpoint: str) -> str:
    shots = segment.get('shots') or []
    shot = (shots[-1] if endpoint == 'last' else shots[0]) if shots else {}
    state = segment.get('end_state' if endpoint == 'last' else 'start_state')
    return (f"Draw one full-frame cinematic still, no panels, captions or text. "
            f"Depict the {'final state AFTER the action, not the next scene' if endpoint == 'last' else 'initial state BEFORE the action'}. "
            f"Location: {segment.get('location', '')}. Characters: {segment.get('characters', [])}. "
            f"Composition guidance: {segment.get('visual_prompt', '')}. State: {state or ''}. Shot/action context: {shot.get('content', '')}. "
            "Use reference sheets to preserve identity, costume, props and set dressing. Freeze a single instant.")
