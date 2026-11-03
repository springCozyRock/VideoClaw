"""Freeze metric inventory, scopes, provenance and known replication gaps."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import hashlib,json,re,subprocess
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, CONFIG_ROOT, INPUT_ROOT, REFERENCES_ROOT, DIRECTOR_ROOT, VBENCH_ROOT, load_json

ROOT = BASELINE_ROOT
RUN = RUN_ROOT
SHORT=['opening_hook','end_hook','escalation_effect','narrative_coherence','character_spatial_continuity','environment_layout_continuity','bgm_emotion_alignment','transition_naturalness']
VISTORY=['scene_alignment','cross_character_consistency','global_character_action','single_character_action']
SCENES={
 'action_006':[(0,67,'屋顶追逐与制服')],
 'cinematic_008':[(0,62,'黄金时刻城市街道镜头语言')],
 'educational_008':[(0,30,'开场'),(30,90,'极线、设备与主线'),(90,150,'跨网省运维模式'),(150,180,'总结'),(180,210,'流程收尾')],
 'music_004':[(0,70,'原创电子音乐舞台')],
 'narrative_074':[(0,34,'公寓日常、灾难与变身'),(34,60,'空中战斗与回归日常')]
}

def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def revision(p):
 return subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()

def main():
 manifest=load_json((CONFIG_ROOT / 'manifest.json'))
 template=((REFERENCES_ROOT / 'short_drama_evaluation_template.txt')).read_text()
 matches=list(re.finditer(r'('+ '|'.join(SHORT)+r')\s*/\s*(drama|scene|clip_pair|scene_pair)\s*:',template))
 rubrics={}
 for i,m in enumerate(matches):
  end=matches[i+1].start() if i+1<len(matches) else len(template)
  rubrics[m.group(1)]={'scope':m.group(2),'rubric':template[m.end():end].strip()}
 assert set(rubrics)==set(SHORT)
 config={
 'generation':{'model':'wan3.0-video','resolution':'720P','ratio':'16:9','audio':True,'duration_sec':469,'shots':22,'cases':[x['case_id'] for x in manifest['cases']]},
 'dataset_scope':{'source':'DirectorBench dataset_original.jsonl','case_count':5,'is_full_paper_benchmark':False,'note':'Five user-selected DirectorBench prompts; transfer of Short-Drama-Bench metrics, not a reproduction of its 50-prompt dataset.'},
 'short_drama':{'paper':'https://arxiv.org/html/2605.22144v1','paper_sections':['3.2','J.5/Table 7','M.1/Figure 10'],'metrics':SHORT,'score_range':[1,5],'paper_judges':['Gemini 3 Pro Preview','Qwen3.5-Omni-Plus','Seed 2.0 Pro'],'available_original_judge':'qwen3.5-omni-plus','missing_original_judges':['Gemini 3 Pro Preview','Seed 2.0 Pro'],'aggregation':'mean across judges, evaluation units, and prompts; missing judges are not imputed','rubrics':rubrics,'video_sampling_fps':1,'sampling_status':'1 FPS for scene/drama audiovisual judging is an explicit implementation choice: paper does not specify this rate for these metrics.','continuity_sampling':'last 3 consecutive decoded frames from preceding clip + first 3 consecutive frames from next clip, before final assembly','continuity_spacing_status':'paper specifies 3+3 frames, not their temporal spacing; consecutive-frame choice is recorded','scope_conflict':'Section 3.2 describes scene-level hooks/coherence; Figure 10 explicitly defines opening_hook as first 10 seconds of drama and narrative_coherence as drama. Primary follows explicit Figure 10; scene-level versions are supplemental and must be labeled.'},
 'vbench':{'metrics':['subject_consistency','background_consistency','motion_smoothness'],'judge':'native automatic modules','source':str((VBENCH_ROOT)),'commit':revision((VBENCH_ROOT)),'sampling':'all decoded frames, native transforms and weights; streamed execution verified against native implementation','frame_cap':None,'temporal_downsampling':False,'aggregation':'native frame weighting for subject/background; mean over videos for motion','runner':'baselines/codex/evaluation/vbench_full.py'},
 'vistorybench':{'metrics':VISTORY,'paper_judge':'ChatGPT 5.0','available_paper_judge':False,'sampling_fps':1,'source':str(Path('/mnt/data/bts/repos/vistorybench')),'commit':revision(Path('/mnt/data/bts/repos/vistorybench')),'supplementary_judge':'qwen3.5-omni-plus','replication_gaps':['Paper does not release its exact video adaptation or frame-to-scene annotation conversion.','Cross-character consistency must use a specified native identity/embedding criterion; do not substitute an invented 1-5 rating for the published consistency score.','Qwen-scored scene/action alignment uses native ViStoryBench prompt templates and must be labeled as a changed-judge supplementary result.'],'scene_action_scale':[0,4]},
 'directorbench':{'paper':'https://arxiv.org/pdf/2605.30090','paper_section':'3 Evaluation Settings and Appendices B-D','paper_judge':'GPT-5.4','available_paper_judge':False,'supplementary_judge':'qwen3.7-plus','source':str((DIRECTOR_ROOT)),'commit':revision((DIRECTOR_ROOT)),'checkpoint_count':40,'submetrics':9,'dimensions':5,'profiles':7,'frames_per_shot':8,'shot_detection_threshold':27.0,'min_shot_duration_sec':0.5,'temperature':0.1,'max_tokens':4096,'registry':'directorbench_registry.json','applicability':'native dynamic activation; inactive checkpoints are NA, never zero-filled','aggregation':'native confidence-aware aggregation and profile-weighted score; retain individual checkpoints and tool fallback traces'},
 'human_evaluation':{'short_drama_raters':20,'directorbench_raters':14,'status':'AWAITING_REAL_ANNOTATORS','requirement':'anonymous randomized units, original Likert rubrics, real human scores; no simulated ratings'},
 'reproducibility':{'freeze_generation_before_judging':True,'keep_original_api_responses':True,'record_frame_timestamps':True,'never_claim_missing_metrics_complete':True}
 }
 dump((CONFIG_ROOT / 'evaluation_protocol.json'),config)
 # The user explicitly selected a unified Qwen judge after the paper audit.
 config['judge_override']={'authorized_by_user':True,'model':'qwen3.5-omni-plus','scope':'all LLM/VLM judges; native automatic feature metrics keep original encoders','paper_comparison_label':'unified Qwen3.5-Omni protocol variant','short_drama_judge_count':1}
 config['short_drama']['active_judges']=['qwen3.5-omni-plus']
 config['short_drama']['aggregation']='mean over valid evaluation units, then equal-weight mean over prompts; one unified judge as explicitly requested'
 config['vistorybench']['active_judge']='qwen3.5-omni-plus'
 config['directorbench']['active_judge']='qwen3.5-omni-plus'
 config['directorbench']['supplementary_judge']='qwen3.5-omni-plus'
 config['directorbench']['asr']={'backend':'faster-whisper','model':'large-v3','beam_size':5,'compute_type':'float16','device':'cuda'}
 dump((CONFIG_ROOT / 'evaluation_protocol.json'),config)
 units={}
 for item in manifest['cases']:
  cid=item['case_id'];plan=load_json((INPUT_ROOT) / cid / 'plan.json');t=0;clips=[]
  for shot in plan['shots']:
   clips.append({'clip_id':shot['shot_id'],'start_sec':t,'end_sec':t+shot['duration_sec'],'description':shot['description']});t+=shot['duration_sec']
  units[cid]={'clips':clips,'scenes':[{'scene_id':i+1,'start_sec':a,'end_sec':b,'description':s} for i,(a,b,s) in enumerate(SCENES[cid])],'scene_boundaries_status':'predeclared screenplay units; model-generated internal cuts may differ. Narrative coda shares its final planned unit because the exact return-home cut is not known before rendering.'}
 dump((CONFIG_ROOT / 'evaluation_units.json'),units)
 # Source profile JSON uses concatenated pretty-printed objects, not strict JSONL.
 text=((DIRECTOR_ROOT / 'data/profiles.jsonl')).read_text();decoder=json.JSONDecoder();pos=0;profiles=[]
 while pos<len(text):
  while pos<len(text) and text[pos] in ' \t\r\n,':pos+=1
  if pos==len(text):break
  obj,end=decoder.raw_decode(text,pos);profiles.append(obj);pos=end
 dump((CONFIG_ROOT / 'directorbench_profiles.json'),profiles)
 dump(RUN/'evaluation/coverage.json',{'VBench':'READY_PENDING_VIDEOS','Short-Drama-Bench':'UNIFIED_QWEN35_READY_PENDING_VIDEOS','ViStoryBench':'UNIFIED_QWEN35; NATIVE_CIDS_VIDEO_ADAPTER_IN_PREPARATION','DirectorBench':'UNIFIED_QWEN35_READY_PENDING_VIDEOS','Human':'AWAITING_REAL_ANNOTATORS'})
 print(json.dumps({'profiles':len(profiles),'short_drama_metrics':len(rubrics),'protocol':str((CONFIG_ROOT / 'evaluation_protocol.json'))},ensure_ascii=False))

if __name__=='__main__':main()
