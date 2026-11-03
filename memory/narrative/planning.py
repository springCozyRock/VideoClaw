"""Versioned intentions, kept separate from observed A²RD memory."""
from dataclasses import asdict
import json
from memory.contracts.models import Segment
from memory.assets.files import digest


def validate_plan(value, request):
    if not isinstance(value, dict) or not isinstance(value.get('segments'), list):
        raise ValueError('Plan requires segments')
    segments = [Segment(**s) for s in value['segments']]
    ids = [s.id for s in segments]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('Plan requires unique segments')
    if request.get('constraints', {}).get('preserve_segment_ids_and_durations'):
        draft = request['story']['storyboard_draft']
        if [(s.id, s.duration) for s in segments] != [(s['id'], s['duration']) for s in draft]:
            raise ValueError('Host segment IDs and duration budgets must be preserved')
    locked = request.get('completed', [])
    if json.loads(json.dumps([asdict(s) for s in segments[:len(locked)]])) != json.loads(json.dumps(locked)):
        raise ValueError('Cannot rewrite completed segments')
    previous = request.get('previous_plan')
    if previous and value.get('beats', [])[:len(locked)] != previous.get('beats', [])[:len(locked)]:
        raise ValueError('Cannot rewrite completed event contracts')
    goals = value.get('goals')
    if not isinstance(goals, list) or not all(isinstance(g, str) and g for g in goals):
        raise ValueError('Plan requires explicit goals')
    if request.get('goals') and goals != request['goals']:
        raise ValueError('Replanning cannot change user goals')
    beats = value.get('beats', [])
    if len(beats) != len(ids):
        raise ValueError('Each segment needs a causal beat')
    for i, beat in enumerate(beats):
        if beat.get('segment_id') != ids[i] or any(d not in ids[:i] for d in beat.get('depends_on', [])):
            raise ValueError('Invalid causal dependency')
        for field in ('purpose', 'expected_begin', 'expected_end'):
            if not isinstance(beat.get(field), str) or not beat[field]:
                raise ValueError('Missing planned state or purpose')
    value = {k:v for k,v in value.items() if k not in ('schema', 'revision_id')}
    value['segments'] = json.loads(json.dumps([asdict(s) for s in segments]))
    return dict(value, schema='aard.plan/1', revision_id=digest(value))
