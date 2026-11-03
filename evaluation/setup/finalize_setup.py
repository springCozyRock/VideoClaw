"""Freeze implementation provenance and explain the runnable remote experiment."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import hashlib,json,subprocess
from pathlib import Path
from workspace_paths import BASELINE_ROOT, PROJECT_ROOT, RUN_ROOT, CONFIG_ROOT, DIRECTOR_ROOT, VBENCH_ROOT, VISTORY_ROOT, load_json
ROOT = BASELINE_ROOT;RUN = RUN_ROOT
def dump(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def main():
 protocol=load_json((CONFIG_ROOT / 'evaluation_protocol.json'))
 protocol['directorbench']['supplementary_judge']='qwen3.5-omni-plus'
 protocol['directorbench']['asr'].update(pinned_revision='edaa852ec7e145841d8ffdb056a99866b5f0a478',startup_guard='Local SHA256-validated weights required; ASR FAILED is fatal, not a fallback score',superseded_runs='experiments/codex_original_720p/evaluation/directorbench_pre_asr_failure_20261016')
 protocol['vistorybench'].update(execution_source=str((VISTORY_ROOT)),adaface_commit='c60eaa786a42c03444f3df7096dbaf9d57ae010d',cross_character_criterion='Native CIDS cids_cross_mean; Hungarian character matching; native face ensemble/CLIP encoders and thresholds',reference_adaptation='No external identity references were provided with these five prompts. Deterministic portraits from first generated appearance clips anchor the metric; this assesses stability against generated anchors, not external identity fidelity.',caption_adaptation='Each 1FPS frame receives its containing planned clip caption; no published per-frame labels are available.',native_single_action_aggregation='Preserves native integer rounding; retains detailed per-character/per-frame scores.',groundingdino_device='cpu',arcface_provider='CPU ONNX; identical antelopev2 weights; native feature mathematics preserved',rate_control='Shared process-safe request pacing and retry cooldown; errors cannot be accepted as zero scores')
 protocol['human_evaluation'].update(status='PREPARED_AWAITING_REAL_ANNOTATORS',package=str(RUN/'human_annotation'),completed_ratings=0,directorbench_criteria=16)
 dump((CONFIG_ROOT / 'evaluation_protocol.json'),protocol)
 manifest=load_json((CONFIG_ROOT / 'manifest.json'));manifest['evaluation']={'judge':'qwen3.5-omni-plus','judge_override_authorized':True,'vbench_frame_cap':None,'vbench_temporal_downsampling':False,'protocol':str((CONFIG_ROOT / 'evaluation_protocol.json'))};dump((CONFIG_ROOT / 'manifest.json'),manifest)
 records=[]
 for directory in [ROOT,(VISTORY_ROOT / 'vistorybench')]:
  paths=(p for p in directory.rglob('*.py') if '__pycache__' not in p.parts) if directory==ROOT else directory.rglob('*.py')
  for p in sorted(paths):records.append({'path':str(p.relative_to(PROJECT_ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 revisions={}
 for name,path in [('VBench',(VBENCH_ROOT)),('DirectorBench',(DIRECTOR_ROOT)),('ViStoryBench_original',Path('/mnt/data/bts/repos/vistorybench'))]:
  revisions[name]={'path':str(path),'commit':subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip(),'working_tree_status':subprocess.check_output(['git','-C',str(path),'status','--porcelain','--untracked-files=no'],text=True)}
 dump((CONFIG_ROOT / 'implementation_manifest.json'),{'files':records,'repositories':revisions,'note':'Shared repositories may contain prior user modifications. Exact copied ViStoryBench sources and project adapters are identified by SHA256; no shared checkout is reset.'})
 (ROOT/'README.md').write_text('''# LongVideoMemory / Codex five-video pilot

All five original-duration videos are in experiments/codex_original_720p/videos/. Total target duration: 469 seconds, 22 generated clips, wan3.0-video, 720P, 16:9, audio. Original DirectorBench metadata is frozen under experiments/codex_original_720p/inputs/*/source.json. Sparse source scripts were expanded into explicit shot plans under experiments/codex_original_720p/inputs/*/plan.json; generation is conditioned on those plans and reference images, not guaranteed to reproduce every requested detail. No timing stretch or padding was used to claim the required duration.

## Live status and results

Read experiments/codex_original_720p/REPORT.md and experiments/codex_original_720p/evaluation/summary.json. Per-stage status is under evaluation/stages/, original requests/responses, timestamps, extracted evidence and raw native results under the corresponding metric family. `COMPLETE` means a stage finished; read protocol and tool traces before comparing scores. The full source/configuration provenance is under configs/codex_original_720p/.

All LLM/VLM judges use qwen3.5-omni-plus, as explicitly requested. Automatic feature metrics keep native encoders. This is a five-prompt protocol variant, not either full benchmark and not the original multi-judge ensemble. Seven DirectorBench profiles evaluate the same five generated videos; these are not 35 separately personalized generations.

VBench runs all decoded frames with native transforms, weights and formulas. Streaming/native parity evidence is in evaluation/vbench_parity/. Short-drama evaluation follows the published Figure 10 rubric/scopes; unspecified sampling choices and the prose/figure scope conflict are disclosed. ViStoryBench runs at 1 FPS with original 0–4 prompt templates and native CIDS. Its unpublished video adapter is implemented explicitly: frame captions inherit the generated-clip script, identity anchors come from generated first-appearance portraits because the source prompts supply no external reference bank. Character-free metrics are NA. Native single-action rounding and all granular results are retained.

## Unattended remote execution

evaluate_watch.py is a server-side background process. Once initialized, screen-off, laptop sleep, SSH disconnect and closing the local Codex window do not terminate that remote process. These events do affect the ability of local Codex to diagnose new problems interactively. Server power loss, process termination and unrecoverable provider errors can still stop progress; no unconditional completion guarantee is made.

dependency_watch.py retries interrupted dependency preparation with bounded attempts for up to eight hours. prepare_asr.py downloads pinned Whisper large-v3 via ordinary HTTPS instead of the failing Xet CAS route, checks official cached LFS SHA256, and validates a local load before enabling DirectorBench. Formal decoding uses CUDA float16, beam 5. ASR failures stop the stage. Earlier fallback-scored DirectorBench runs are excluded and archived under directorbench_pre_asr_failure_20261016/. Other native unavailable-tool/fallback traces remain visible in each diagnostic report.

API transport uses a cross-process lock, request pacing and cooldown after provider 429. Successful judge responses are cached. Native judge errors abort rather than becoming score zero. Check provider_pause.json and stage WAITING_PROVIDER statuses. The watcher resumes when the retry time arrives.

Project .env credentials override stale shared-shell variables. Never print the key or include .env in artifacts. Do not resubmit video generation tasks whose IDs/results already exist. Do not start a second watcher: a process lock prevents overlap. Watcher PID and logs are under experiments/codex_original_720p/. To resume after an intentional stop, run `python3 -u baselines/codex/operations/evaluate_watch.py` from the LongVideoMemory directory with stdout/stderr redirected and stdin detached. Existing verified results are reused.

## Human evaluation

human_annotation/ contains randomized anonymous assets and empty forms for 20 Short-Drama-Bench raters and 14 DirectorBench raters (16 criteria). The coordinator mapping must stay private. Real annotators are still required; zero human ratings have been collected. Human scores are never generated by a model or inferred from automatic scores.
''')
 print('Protocol, provenance and remote-run documentation updated')
if __name__=='__main__':main()
