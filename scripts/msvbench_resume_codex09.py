#!/usr/bin/env python3
"""Continue only the authorized story 09; reuse all existing plans and API receipts."""
from pathlib import Path
import os,json,subprocess,time,fcntl,sys
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'experiments/msvbench_agents_20261018/codex_composition'
REPAIR=ROOT/'experiments/msvbench_repair_20261019'
sys.path.insert(0,str(ROOT/'baselines/codex'))
from adapter.supervision import experiment_lock,run_process
from adapter.integrity import verify_execution
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False))
with experiment_lock(RUN,'msvbench') as lock:
 verify_execution()
 old=next((RUN/'runtime/generation/msvbench_generation/1018_0938_expert_failed').glob('failed_narrative_09_*'))
 name=old.name.removeprefix('failed_')
 original=RUN/'runtime/generation/generate_materials'/name
 if not original.exists():original.symlink_to(old,target_is_directory=True)
 workspace=RUN/'runtime/generation/workspace'
 prompt=f"""Continue the already-authorized MSVBench story 09 only, using the existing frozen lvm-narrative-wan3 Composition Skill and foundation skills. This is recovery from an upstream QwenAgentError, not a new story or a re-plan.
Read AGENTS.md and applicable Skill instructions. Use get-output-dir; LVM_TOOL_OUTPUT pins this recovery to {old}. Do not inspect any other case or old pilot. Do not modify frozen skills, shared environments or credentials.
Existing story 09 plan, observations, references, QA and clips are in {old}. The original absolute output path {original} now resolves there as well. Preserve plan decisions, durations, character/style blocks and all accepted existing clips. Consult the actual current plan and receipts; some clip files exist although QA is pending. Finish checks on those clips, then only generate genuinely missing segments 24/25 if their original request has not already been submitted. Never issue another paid POST after an unknown submission; preserve and report the blocked state. Do not edit API ledgers or change prompts merely to bypass unknown-submission protection.
Use the same configured wan2.7-image / wan3.0-video and qwen3.5-omni-plus tools. Do not redesign identities or rewrite prompts to evade provider content/IP refusals. Keep any already-recorded reference substitutions and retry-budget deviations visible in the final report, and obey the frozen retry budget for new work.
Preserve the complete official 25-shot order. Inputs are {ROOT/'experiments/msvbench_agents_20261018/inputs/09'}. Original requirements are {RUN/'dataset/narrative/09/requirements.txt'}.
If complete, merge final.mp4 and perform required final checks. Write evaluation_manifest.json with story='09', absolute final_video, and exactly 25 shots in official order. Each shot entry must have official_shot_index, absolute path to its selected clip, start_sec/end_sec LOCAL TO THAT CLIP (normally 0..measured duration), and description. Do not use cumulative final-video offsets with per-clip paths. Keep all native planning and actual durations; no fixed five-second rule.
If blocked, write recovery_status.json with precise reason and receipts; do not mark a partial film complete. Retain all existing media. Do not use rm-style deletion. Finish by stating actual output, coverage and deviations."""
 (REPAIR/'codex09_resume_prompt.txt').write_text(prompt)
 env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',LVM_PROJECT_ROOT=str(ROOT),
  OUTPUT_DIR=str(RUN/'runtime/generation/generate_materials'),LVM_TOOL_OUTPUT=str(old),
  CODEX_THREAD_NAME='narrative_09_lvm-narrative-wan3_recovery',
  MSVBENCH_AGENT_PROXY_URL='http://127.0.0.1:19083',
  MSVBENCH_DNS_FALLBACK=str(REPAIR/'resolver_fallback.json'),
  PYTHONPATH=str(REPAIR/'network_bootstrap')+':'+str(ROOT/'scripts'),
  LVM_CODEX_REASONING='xhigh')
 env['PATH']=str(ROOT/'.venvs/codex_composition/bin')+':'+env.get('PATH','')
 env.pop('CODEX_THREAD_ID',None)
 cmd=[str(ROOT/'baselines/codex/msvbench_composition/codex_provider.py'),'exec',
 '--skip-git-repo-check','--json','-C',str(workspace),'--sandbox','workspace-write',
 '--ephemeral','--ignore-user-config','--disable','memories','--disable','multi_agent',
 '-c','approval_policy="never"','-c','sandbox_workspace_write.network_access=true',
 '--add-dir',str(RUN),'--model','qwen3.8-max-0902','-']
 with (REPAIR/'codex09_resume_prompt.txt').open() as inp,(REPAIR/'codex09_resume.events.jsonl').open('w') as out,(REPAIR/'codex09_resume.stderr.log').open('w') as err:
  rc=run_process(cmd,stdin=inp,stdout=out,stderr=err,cwd=workspace,env=env,
                 lock_fd=lock.fileno(),status_path=REPAIR/'codex09_resume_process.json')
 if rc:raise SystemExit(rc)
 # Collect only if a complete, valid manifest was produced.
 sys.path.insert(0,str(ROOT/'scripts'))
 import msvbench_agents_run as runner
 row=next(x for x in json.loads((ROOT/'configs/msvbench_agents_20261018/manifest.json').read_text())['stories'] if x['story']=='09')
 try:runner.collect_codex(row)
 except Exception as ex:save(REPAIR/'codex09_collection_error.json',{'error':str(ex),'time':time.time()})
