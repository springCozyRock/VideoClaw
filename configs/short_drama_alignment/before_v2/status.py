#!/usr/bin/env python3
"""Read-only status for the LongVideoMemory workspace; no paid API calls."""
import argparse,json,os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'baselines/codex'))
from workspace_paths import RUN_ROOT,CONFIG_ROOT,load_json
RUN=RUN_ROOT
def read(path,default=None):
 try:return load_json(path)
 except (FileNotFoundError,ValueError):return default
def snapshot():
 manifest=read(CONFIG_ROOT/'manifest.json',{'cases':[]});cases=[]
 for case in manifest['cases']:
  cid=case['case_id'];stages={name:read(RUN/'evaluation/stages'/cid/(name+'.json'),{}).get('status','WAITING') for name in ['vbench','short_drama','vistorybench','directorbench']}
  profiles=len(list((RUN/'evaluation/directorbench'/cid).glob('profile_*/result.json')))
  cases.append({'case_id':cid,'generation':read(RUN/'cases'/cid/'generation.json',{}).get('status','WAITING'),'directorbench_profiles':profiles,'expected_profiles':7,'evaluation_stages':stages})
 processes=[]
 for name in ['evaluation_watch','bgm_policy','audit_validity','cost_audit','dependency_watch']:
  path=RUN/(name+'.pid');item={'name':name,'alive':False}
  if path.exists():
   try:
    pid=int(path.read_text());item['pid']=pid
    cmd=Path('/proc/%d/cmdline'%pid).read_bytes().decode()
    item['alive']=str(ROOT) in cmd and bool(cmd)
    if item['alive']:
     status=Path('/proc/%d/status'%pid).read_text().splitlines();item['state']=next((x.split(':',1)[1].strip() for x in status if x.startswith('State:')),'unknown')
   except (FileNotFoundError,ValueError,PermissionError):pass
  processes.append(item)
 cost=read(RUN/'evaluation/cost_ledger.json',{});validity=read(RUN/'evaluation/validity.json',{});bgm=read(RUN/'evaluation/bgm_skip_status.json',{})
 finished=read(RUN/'evaluation/finished.json',{})
 return {'checked_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'root':str(ROOT),'run':str(RUN),'memory_work':'PAUSED_BY_USER','evaluation_work':finished.get('status','CONTINUE_AS_REQUESTED'),'watcher':read(RUN/'evaluation/watch_status.json',{}),'finished':read(RUN/'evaluation/finished.json'),'cases':cases,'directorbench_profiles':sum(x['directorbench_profiles'] for x in cases),'expected_directorbench_profiles':35,'bgm_policy_applied_profiles':bgm.get('policy_applied_profiles'),'bgm_metric':'SKIPPED_BY_USER','validity':validity.get('status'),'mobileviclip':read(RUN/'evaluation/mobileviclip_environment.json',{}).get('status'),'cost':{k:cost.get(k) for k in ['updated_at','generation_subtotal','recorded_judge_subtotal','recorded_api_total_estimate','recorded_judge_calls','status']},'processes':processes}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--json',action='store_true');args=p.parse_args();d=snapshot()
 if args.json:print(json.dumps(d,ensure_ascii=False,indent=2));return
 print('LongVideoMemory 状态 · '+d['checked_at'])
 print('Memory 接入：已暂停；评测：'+('自动执行已完成，仍需核对有效性缺口与人工评分。' if d['evaluation_work']=='AUTOMATIC_EVALUATION_COMPLETE' else '继续。'))
 print('DirectorBench profiles: %d/%d；BGM: %s'%(d['directorbench_profiles'],d['expected_directorbench_profiles'],d['bgm_metric']))
 for c in d['cases']:
  print('%-18s video=%-10s director=%d/7  VBench=%s  ShortDrama=%s  ViStory=%s'%(c['case_id'],c['generation'],c['directorbench_profiles'],c['evaluation_stages']['vbench'],c['evaluation_stages']['short_drama'],c['evaluation_stages']['vistorybench']))
 total=d['cost'].get('recorded_api_total_estimate')
 print('已记录 API 原价估算：'+('%.2f 元'%total if total is not None else '待统计')+'；与实际账户账单可能不同。')
 print('有效性：%s；MobileViCLIP：%s'%(d['validity'],d['mobileviclip']))
 print('进程：'+', '.join(x['name']+'='+('running' if x['alive'] else 'not running') for x in d['processes']))
if __name__=='__main__':main()
