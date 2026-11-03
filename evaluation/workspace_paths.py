"""Canonical workspace paths and read-time relocation of historical records.

Raw API requests, responses and evidence retain their original bytes. This
module resolves their old absolute file paths in memory, without aliases on disk.
"""
import json
import os
import re
from pathlib import Path

BASELINE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BASELINE_ROOT
RUN_ID = os.environ.get('LVM_EVALUATION_RUN_ID', 'codex_original_720p')
# Experiment and configuration directories can have independent names.
_DEFAULT_CONFIG_IDS = {'codex_composition_wan3_720p': 'codex_composition_wan3'}
CONFIG_ID = os.environ.get('LVM_EVALUATION_CONFIG_ID', _DEFAULT_CONFIG_IDS.get(RUN_ID, RUN_ID))
if not all(re.fullmatch(r'[a-zA-Z0-9_]+', value) for value in (RUN_ID, CONFIG_ID)):
    raise ValueError('Invalid evaluation run or configuration id')
CONFIG_ROOT = PROJECT_ROOT / 'configs' / CONFIG_ID
RUN_ROOT = PROJECT_ROOT / 'experiments' / RUN_ID
INPUT_ROOT = RUN_ROOT / 'inputs'
REFERENCES_ROOT = PROJECT_ROOT / 'docs' / 'references'
CACHE_ROOT = PROJECT_ROOT / '.cache'
ENV_FILE = PROJECT_ROOT / '.env'
VISTORY_ENV = PROJECT_ROOT / '.venvs' / 'vistorybench'
MOBILE_ENV = PROJECT_ROOT / '.venvs' / 'mobileviclip'
DIRECTOR_ROOT = PROJECT_ROOT / 'benchmarks' / 'directorbench'
VBENCH_ROOT = PROJECT_ROOT / 'benchmarks' / 'vbench'
VISTORY_ROOT = PROJECT_ROOT / 'benchmarks' / 'vistorybench'
MOBILE_ROOT = PROJECT_ROOT / 'third_party' / 'mobileviclip'
VIDEOCLAW_ROOT = PROJECT_ROOT

CONFIG_NAMES = (
    'manifest.json', 'evaluation_protocol.json', 'evaluation_units.json',
    'directorbench_profiles.json', 'directorbench_registry.json',
    'vbench_prompts.json', 'model_catalog.json', 'implementation_manifest.json',
)

SCRIPT_GROUPS = {
    'generation': ('prepare.py', 'runner.py'),
    'evaluation': (
        'eval_director.py', 'eval_short_drama.py', 'eval_vistory.py',
        'eval_media.py', 'vbench_full.py', 'director_metric_policy.py',
        'audit_validity.py',
    ),
    'operations': (
        'evaluate_watch.py', 'dependency_watch.py', 'cost_audit.py',
        'api_throttle.py',
    ),
    'setup': (
        'bootstrap_vistory.py', 'prepare_asr.py', 'configure_eval.py',
        'prepare_human.py', 'finalize_setup.py',
    ),
    'diagnostics': ('transport_smoke.py',),
}

def relocation_pairs():
    old = PROJECT_ROOT / 'Codex'
    pairs = [
        (old / 'runs/original_720p', RUN_ROOT),
        (old / 'samples', INPUT_ROOT),
        (old / 'references', REFERENCES_ROOT),
        (old / 'deps/vistorybench', VISTORY_ROOT),
        (old / 'deps/MobileViCLIP', MOBILE_ROOT),
        (old / '.venv_vistory', VISTORY_ENV),
        (old / '.venv_mobileviclip', MOBILE_ENV),
        (old / '.cache', CACHE_ROOT),
        (old / '.env', ENV_FILE),
        (old / 'REPORT.md', RUN_ROOT / 'REPORT.md'),
    ]
    pairs.extend((old / name, CONFIG_ROOT / name) for name in CONFIG_NAMES)
    for group, names in SCRIPT_GROUPS.items():
        for name in names:
            pairs.append((old / name, BASELINE_ROOT / group / name))
            pairs.append((BASELINE_ROOT / name, BASELINE_ROOT / group / name))
    pairs.extend([
        (old, BASELINE_ROOT),
        (PROJECT_ROOT / 'VideoClaw', VIDEOCLAW_ROOT),
        (PROJECT_ROOT / 'DirectorBench', DIRECTOR_ROOT),
        (PROJECT_ROOT / 'VBench', VBENCH_ROOT),
    ])
    return sorted(((str(a), str(b)) for a, b in pairs), key=lambda item: len(item[0]), reverse=True)

def relocate_path(value):
    """Map only a complete legacy path prefix, never text inside a prompt."""
    value = str(value)
    for old, new in relocation_pairs():
        if value == old or value.startswith(old + '/'):
            return new + value[len(old):]
    return value

def resolve_record_paths(value):
    if isinstance(value, dict):
        return {key: resolve_record_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_record_paths(item) for item in value]
    if isinstance(value, str) and value.startswith(str(PROJECT_ROOT) + '/'):
        return relocate_path(value)
    return value

def load_json(path):
    return resolve_record_paths(json.loads(Path(path).read_text()))
