"""Invoice-independent list-price estimate from deduplicated recorded usage."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import argparse,collections,json,os,time
from datetime import datetime,timezone
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, CONFIG_ROOT, load_json
ROOT = BASELINE_ROOT;RUN = RUN_ROOT
PRICES={'video_720p_cny_per_second':0.6,'qwen3.5-omni-plus':{'non_audio_input_per_million':7,'audio_input_per_million':53,'text_output_per_million':40}}
def write(path,value):
 temp=path.with_name(path.name+'.%d.tmp'%os.getpid());temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
def audit():
 records={};unparsed=0
 for p in RUN.rglob('*.json'):
  if p.name in ['request.json','summary.json','result.json','evidence.json','story.json','cost_usage_snapshot.json','cost_ledger.json','validity.json']:continue
  if 'cost_' in p.name:continue
  try:d=load_json(p)
  except (ValueError,UnicodeError,FileNotFoundError):unparsed+=1;continue
  if not isinstance(d,dict):continue
  chunks=d.get('chunks',[])
  if d.get('usage'):chunks=chunks+[d]
  for chunk in chunks:
   if not isinstance(chunk,dict) or not chunk.get('usage'):continue
   usage=chunk['usage'];rid=chunk.get('id') or chunk.get('request_id')
   if rid and ('prompt_tokens' in usage or 'input_tokens' in usage):records[rid]={'model':chunk.get('model','UNKNOWN'),'usage':usage,'source':str(p)}
 models={};families={};unknown=[]
 for rid,record in records.items():
  model=record['model'];usage=record['usage'];input_tokens=usage.get('prompt_tokens',usage.get('input_tokens',0));output_tokens=usage.get('completion_tokens',usage.get('output_tokens',0));details=usage.get('prompt_tokens_details',{})
  audio=details.get('audio_tokens',0);non_audio=input_tokens-audio
  rates=PRICES.get(model);cost=(non_audio*rates['non_audio_input_per_million']+audio*rates['audio_input_per_million']+output_tokens*rates['text_output_per_million'])/1e6 if rates else None
  if rates is None:unknown.append(rid)
  values={'calls':1,'input_tokens':input_tokens,'audio_input_tokens':audio,'non_audio_input_tokens':non_audio,'text_output_tokens':output_tokens,'list_price_estimate_cny':cost or 0}
  target=models.setdefault(model,collections.Counter());target.update(values)
  path=Path(record['source']);rel=path.relative_to(RUN);family=rel.parts[1] if rel.parts[0]=='evaluation' and len(rel.parts)>1 else rel.parts[0]
  families.setdefault(family,collections.Counter()).update(values)
 manifest=load_json((CONFIG_ROOT / 'manifest.json'));generation=[]
 for case in manifest['cases']:
  generation.append({'case_id':case['case_id'],'output_seconds':case['duration_sec'],'list_price_estimate_cny':case['duration_sec']*PRICES['video_720p_cny_per_second']})
 video=sum(x['list_price_estimate_cny'] for x in generation);judges=sum(x['list_price_estimate_cny'] for x in models.values())
 ledger={'updated_at':datetime.now(timezone.utc).isoformat(),'status':'PARTIAL_LIST_PRICE_ESTIMATE_NOT_INVOICE','currency':'CNY','generation':generation,'generation_subtotal':video,'recorded_judge_calls':len(records),'judge_models':models,'judge_families':families,'recorded_judge_subtotal':judges,'recorded_api_total_estimate':video+judges,'unknown_price_call_ids':unknown,'price_basis':PRICES,'price_sources':['https://help.aliyun.com/zh/model-studio/wan3-0-video','https://help.aliyun.com/zh/model-studio/qwen3-5-omni-plus'],'limitations':['This is the project\'s recorded-usage list-price estimate, not a cloud billing export.','Deduplicates provider response IDs across cache and archived copies; retained earlier evaluation, successful retries and smoke calls are included.','Missing/unpersisted responses and early probes outside experiments/codex_original_720p may be absent; model usage is still growing.','No free quota, account discount or promotion is subtracted.','Local GPU, storage, traffic and Codex subscription/usage are not monetized because no resource billing rates were supplied.'],'source_records':records,'unparsed_files':unparsed}
 write(RUN/'evaluation/cost_ledger.json',ledger)
 print('Recorded list-price cost: video %.2f + judges %.2f = %.2f CNY (%d unique calls)'%(video,judges,video+judges,len(records)),flush=True)
 return (RUN/'evaluation/finished.json').exists()
def main():
 p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');args=p.parse_args()
 while True:
  finished=audit()
  if not args.watch or finished:return
  time.sleep(120)
if __name__=='__main__':main()
