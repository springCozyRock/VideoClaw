"""Passive provider-call accounting. No Memory, prompting or workflow decisions."""
import functools
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid


def save(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str));tmp.replace(path)


def token_cost(model, usage):
    inp=usage.get('input_tokens',usage.get('prompt_tokens'))
    out=usage.get('output_tokens',usage.get('completion_tokens'))
    if inp is None or out is None:return None
    if model.startswith('qwen3.7-plus'):
        a,b=(2,8) if inp<=262144 else (6,24)
        cached=usage.get('cached_tokens',usage.get('prompt_tokens_details',{}).get('cached_tokens',usage.get('input_tokens_details',{}).get('cached_tokens',0)))
        return ((inp-cached)*a+cached*a*.2+out*b)/1e6
    if model=='qwen3.5-omni-plus':return (inp*7+out*40)/1e6
    return None


def image_count(obj):
    if isinstance(obj,list):return sum(image_count(x) for x in obj)
    if isinstance(obj,dict):
        return sum(1 if k=='image' and isinstance(v,str) else image_count(v) for k,v in obj.items())
    return 0


class Meter:
    def __init__(self,run):
        self.run=Path(run);self.stage='initialization';self.lock=threading.Lock()

    def begin(self,kind,model,request=None):
        with self.lock:
            if kind=='image':
                for p in (self.run/'meter/calls').glob('*.json'):
                    old=json.loads(p.read_text())
                    if old['kind']=='image' and old['status'] in ('SUBMITTING','UNKNOWN'):
                        # Concurrent active calls are fine; an interrupted process is not.
                        if old['status']=='UNKNOWN':raise RuntimeError('Unreconciled image submission; inspect ledger')
            identity=uuid.uuid4().hex
            value=dict(id=identity,kind=kind,model=model,stage=self.stage,status='SUBMITTING',started_at=time.time())
            if request is not None:
                payload={k:v for k,v in request.items() if k not in ('api_key','headers')}
                value['request_sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
            save(self.run/'meter/calls'/ (identity+'.json'),value)
            return value

    def end(self,value,status,**fields):
        value.update(status=status,ended_at=time.time(),**fields)
        value['elapsed_sec']=value['ended_at']-value['started_at']
        save(self.run/'meter/calls'/ (value['id']+'.json'),value)

    def sdk_wrapper(self,original,kind):
        @functools.wraps(original)
        def call(*args,**kwargs):
            rec=self.begin(kind,kwargs.get('model','unknown'),kwargs)
            try:
                rsp=original(*args,**kwargs)
                doc=json.loads(json.dumps(dict(rsp),default=str))
                code=doc.get('status_code',getattr(rsp,'status_code',None))
                usage=doc.get('usage') or {}
                count=image_count(doc.get('output',{})) if kind=='image' else None
                self.end(rec,'SUCCEEDED' if code==200 else 'REJECTED',http_status=code,
                         request_id=doc.get('request_id'),usage=usage,output_images=count,
                         output=doc.get('output') if kind=='llm' else None)
                return rsp
            except Exception as exc:
                self.end(rec,'UNKNOWN',error_type=type(exc).__name__)
                raise
        return call

    def install(self):
        import dashscope
        from dashscope.aigc.image_generation import ImageGeneration
        ImageGeneration.call=staticmethod(self.sdk_wrapper(ImageGeneration.call,'image'))
        dashscope.MultiModalConversation.call=staticmethod(self.sdk_wrapper(dashscope.MultiModalConversation.call,'llm'))
        dashscope.Generation.call=staticmethod(self.sdk_wrapper(dashscope.Generation.call,'llm'))
        # Qwen Omni needs Chat Completions. This is the same transport compatibility
        # mapping as the prior run, with original native judge prompts unchanged.
        from models.llm_client import LLM
        from msvbench_qwen import QwenAPI
        original=LLM.query;meter=self
        def query(agent,prompt,image_urls=None,model='qwen3.7-plus',safe_content=True,task_id=None,web_search=False):
            if model!='qwen3.5-omni-plus':
                return original(agent,prompt,image_urls or [],model,safe_content,task_id,web_search)
            rec=meter.begin('llm',model,dict(prompt=prompt,images=image_urls or []))
            api=QwenAPI();api.out=meter.run/'judge_calls'/rec['id']
            try:
                result=api.generate_multimodal(prompt,image_paths=image_urls or [])
                docs=[json.loads(p.read_text()) for p in api.out.glob('*/response.json')]
                usage={}
                for doc in docs:
                    for chunk in doc.get('chunks',[]):
                        if chunk.get('usage'):usage=chunk['usage']
                retry_errors=len(list(api.out.glob('*/error_*.json')))
                meter.end(rec,'SUCCEEDED',usage=usage,transport_retry_errors=retry_errors)
                return result
            except Exception as exc:
                meter.end(rec,'UNKNOWN',error_type=type(exc).__name__)
                raise
        LLM.query=query

    def summarize(self,wall_sec,duration_sec=None):
        calls=[json.loads(p.read_text()) for p in (self.run/'meter/calls').glob('*.json')]
        breakdown={'images':0.0,'videos':0.0,'planning_and_judging':0.0}
        missing=[];images=0;tokens_in=0;tokens_out=0
        for c in calls:
            if c['status']=='SUCCEEDED':
                if c['kind']=='image':
                    count=c.get('output_images')
                    if not count:missing.append(c['id']+': image output count missing')
                    else:images+=count;breakdown['images']+=count*.2
                else:
                    usage=c.get('usage') or {};cost=token_cost(c['model'],usage)
                    if cost is None:missing.append(c['id']+': token usage or rate missing')
                    else:breakdown['planning_and_judging']+=cost
                    tokens_in+=usage.get('input_tokens',usage.get('prompt_tokens',0))
                    tokens_out+=usage.get('output_tokens',usage.get('completion_tokens',0))
                if c.get('transport_retry_errors'):missing.append(c['id']+': earlier transport attempts may have unreported usage')
            elif c['status'] in ('UNKNOWN','SUBMITTING'):missing.append(c['id']+': unknown provider outcome')
        tasks=[json.loads(p.read_text()) for p in (self.run/'tasks').glob('*.json') if not p.name.endswith('.response.json')]
        seconds=0
        for task in tasks:
            if task.get('status')=='SUCCEEDED':seconds+=task['duration_sec']
            elif task.get('status') not in ('FAILED','CANCELED','REJECTED','RATE_LIMITED'):
                missing.append('video task outcome unresolved: '+str(task.get('task_id')))
        breakdown['videos']=seconds*.6
        total=sum(breakdown.values());minutes=duration_sec/60 if duration_sec else None
        result=dict(currency='CNY',cost_basis='official Beijing list prices, not account bill; excludes discounts/free quota and server rental',
                    sample_count=1,estimated_total_cny=total,breakdown_cny=breakdown,
                    usage_complete=not missing,unresolved_items=missing,generated_images=images,
                    successful_generated_video_seconds=seconds,input_tokens=tokens_in,output_tokens=tokens_out,
                    wall_clock_sec=wall_sec,final_duration_sec=duration_sec,
                    cny_per_finished_minute=total/minutes if minutes else None,
                    wall_minutes_per_finished_minute=wall_sec/60/minutes if minutes else None,
                    api_calls=len(calls),video_tasks=len(tasks),memory_enabled=False)
        save(self.run/'cost_time.json',result);return result
