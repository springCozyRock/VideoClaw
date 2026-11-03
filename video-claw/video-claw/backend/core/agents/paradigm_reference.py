"""Preparation of auditable per-segment conditioning assets for four paradigms."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from core.generation_paradigms import (
    MODES, conditioning, file_identity, fingerprint, frame_prompt, grid_groups,
    resolve_paradigm, selected_references, slice_grid,
)


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


async def prepare_references(agent, data: dict, intervention: dict | None = None) -> dict:
    from models.image_client import ImageClient

    paradigm = resolve_paradigm(data, agent._session_meta(data))
    artifacts = agent._session_artifacts(data)
    episodes = artifacts.get('storyboard', {}).get('episodes', [])
    segments = [s for ep in episodes for s in ep.get('segments', [])]
    if not segments:
        raise ValueError('Complete storyboard before preparing generation inputs')
    ids = [s['segment_id'] for s in segments]
    if len(set(ids)) != len(ids):
        raise ValueError('Storyboard segment IDs must be unique')
    assets = artifacts.get('character_design', {})
    old_art = artifacts.get('reference_generation', {})
    old = {s['id']: s for s in old_art.get('scenes', [])}
    intervention = intervention or {}
    selected = intervention.get('selected_images', {})
    regen = set(intervention.get('regenerate_scenes', []))
    unknown = (set(selected) | regen) - set(ids)
    if unknown:
        raise ValueError(f'Unknown segments: {sorted(unknown)}')
    if selected:
        # Explicit version selections belong to their original unit and paradigm.
        if old_art.get('generation_paradigm') != paradigm:
            raise ValueError('Cannot select a version from a different paradigm')
        for key, path in selected.items():
            if path not in old[key].get('versions', []):
                raise ValueError('Select only a recorded version of this unit')
            old[key] = {**old[key], 'selected': path, 'first_frame': path}
            conditioning(old[key], paradigm)
        return {'payload': {**old_art, 'scenes': [old[k] for k in ids]}, 'stage_completed': True}

    # No model initialization or calls on the multi-reference branch.
    client = ImageClient() if paradigm != 'multiref2v' else None
    root = Path('code/result/image') / str(data['session_id']) / 'paradigms' / paradigm
    style = agent._get_style_prompt(data.get('style', 'realistic'))
    image_model = data.get('image_it2i_model')
    text_model = data.get('image_t2i_model')
    refs = {s['segment_id']: selected_references(s, assets) for s in segments}
    scenes = []

    def render(prompt, references, directory, unit):
        agent._check_cancel()
        directory.mkdir(parents=True, exist_ok=True)
        model = image_model if references else text_model
        if not model:
            raise ValueError('Missing image model configuration')
        paths, used_prompt, rewrite = agent._generate_image_with_doctor(
            client, prompt=f'{style}\n{prompt}', model=model,
            llm_model=data.get('llm_model', ''), context={'segment_id': unit, 'paradigm': paradigm},
            image_paths=references or None, session_id=str(data['session_id']),
            save_dir=str(directory), video_ratio=data.get('video_ratio', '16:9'), resolution='2K')
        if not paths or not Path(paths[0]).is_file():
            raise RuntimeError('Image model returned no local image')
        return str(Path(paths[0]).absolute()), used_prompt, rewrite

    def evaluate(path, segment, prompt):
        result = agent._evaluate_with_vlm(path, segment,
            (segment.get('shots') or [{}])[0].get('content', ''), prompt,
            vlm_model=data.get('vlm_model') or 'qwen3.5-plus')
        accepted = bool(result.get('is_acceptable', result.get('score', 0) >= 7)) and not result.get('hard_failures')
        return accepted, result

    def render_frame(segment, endpoint, references, directory):
        prompt = frame_prompt(segment, endpoint)
        # Evaluate the end state itself rather than the first shot's action.
        evaluation_segment = {**segment, 'shots': [{'content': prompt}]}
        for attempt in range(3):
            path, used, rewrite = render(prompt, references, directory, segment['segment_id'])
            accepted, quality = evaluate(path, evaluation_segment, prompt)
            if accepted:
                return path, used, rewrite, quality
            prompt = agent._apply_eval_feedback_to_visual_prompt(prompt, quality, attempt)
        raise RuntimeError(f"{segment['segment_id']} {endpoint} frame failed VLM validation: {quality}")

    def publish(record):
        scenes.append(record)
        agent._report_progress('参考图', f"{paradigm}: {record['id']}",
                               int(100 * len(scenes) / len(segments)),
                               {'asset_complete': {'type': 'scenes', **record}, 'persist': True})

    def execute():
        groups = grid_groups(episodes) if paradigm == 'grid2v' else [[s] for s in segments]
        for group in groups:
            agent._check_cancel()
            unique_refs = list(dict.fromkeys(r['path'] for s in group for r in refs[s['segment_id']]))
            source = {'schema': 'videoclaw.paradigm/1', 'generation_paradigm': paradigm,
                      'segments': group, 'references': [file_identity(p) for p in unique_refs],
                      'style': style, 'ratio': data.get('video_ratio', '16:9'),
                      'image_models': [image_model, text_model]}
            source_hash = fingerprint(source)
            directory = root / source_hash
            checkpoint = directory / 'manifest.json'
            cached = None
            if checkpoint.exists() and not any(s['segment_id'] in regen for s in group):
                cached = json.loads(checkpoint.read_text())
                try:
                    for r in cached['scenes']:
                        conditioning(r, paradigm)
                except (ValueError, KeyError):
                    cached = None
            if cached:
                for record in cached['scenes']:
                    # Preserve explicit UI selections across resume.
                    prior = old.get(record['id'], {})
                    if prior.get('source_hash') == source_hash and prior.get('selected') in record.get('versions', []):
                        record = {**record, 'selected': prior['selected'], 'first_frame': prior['selected']}
                    publish(record)
                continue
            # Every regeneration has its own immutable asset directory.
            version_dir = directory / uuid4().hex[:12]
            records = []
            if paradigm == 'grid2v':
                cells = '\n'.join(f"Cell {i + 1}: {frame_prompt(s, 'first')}" for i, s in enumerate(group))
                prompt = ('Draw a precise 2x2 cinematic storyboard grid, four equal borderless cells, '
                          'read left to right, top to bottom. All cells have the same aspect ratio as the canvas. '
                          'Maintain identical characters, costumes, objects and locations across cells. '
                          'No labels, text, gutters or decorative borders. Unused cells must be blank.\n' + cells)
                for attempt in range(3):
                    image, used, rewrite = render(prompt, unique_refs, version_dir / str(attempt), group[0]['segment_id'])
                    records = slice_grid(image, group, version_dir / str(attempt))
                    rejected = []
                    for record, segment in zip(records, group):
                        accepted, quality = evaluate(record['first_frame'], segment, frame_prompt(segment, 'first'))
                        record.update(visual_prompt=used, rewrite_result=rewrite, quality=quality)
                        if not accepted:
                            rejected.append({'unit': segment['segment_id'], 'issues': quality})
                    if not rejected:
                        break
                    prompt += '\nCorrect these panel defects: ' + json.dumps(rejected, ensure_ascii=False)
                else:
                    raise RuntimeError(f'Grid failed VLM validation: {rejected}')
            else:
                for segment in group:
                    key = segment['segment_id']
                    record = {'unit_id': key}
                    if paradigm != 'multiref2v':
                        first, prompt, rewrite, quality = render_frame(segment, 'first', unique_refs, version_dir)
                        record.update(first_frame=first, visual_prompt=prompt, rewrite_result=rewrite, quality=quality)
                        if paradigm == 'fflf2v':
                            last, last_prompt, _, last_quality = render_frame(segment, 'last',
                                                         list(dict.fromkeys([first] + unique_refs)), version_dir)
                            record.update(last_frame=last, last_frame_prompt=last_prompt, last_quality=last_quality)
                    records.append(record)
            for record, segment in zip(records, group):
                key = segment['segment_id']
                first = record.get('first_frame', '')
                versions = [first] if first else []
                previous = old.get(key, {})
                # Version history is limited to the same source; no cross-story reuse.
                if previous.get('source_hash') == source_hash:
                    versions = list(dict.fromkeys(previous.get('versions', []) + versions))
                record.update(id=key, name=key, index=ids.index(key) + 1, status='done',
                              selected=first, versions=versions, references=refs[key],
                              generation_paradigm=paradigm, conditioning_mode=MODES[paradigm],
                              source_hash=source_hash, segment_hash=fingerprint(segment),
                              reference_identity=[file_identity(p) for p in unique_refs],
                              source_shot_ids=[s.get('shot_id') or s.get('id') or f'{key}:shot:{i+1}'
                                               for i, s in enumerate(segment.get('shots', []))],
                              description=segment.get('shots', [{}])[0].get('content', '') if segment.get('shots') else '')
                conditioning(record, paradigm)
                publish(record)
            _save(checkpoint, {'source': source, 'scenes': records})
        return {'payload': {'session_id': data['session_id'], 'generation_paradigm': paradigm,
                            'unit_type': 'segment', 'scenes': scenes}, 'stage_completed': True}

    return await asyncio.get_running_loop().run_in_executor(None, execute)
