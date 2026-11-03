#!/usr/bin/env python3
"""Paper Figure-10 Short-Drama-Bench with disclosed Qwen-only adaptations.

--prepare writes the plan without extracting media or making API requests.
New results live in short_drama_figure10_aligned_v2; legacy scores are retained.
"""
import sys as _sys
from pathlib import Path as _Path
_CODEX=_Path(__file__).resolve().parents[1]
_sys.path[:0]=[str(_CODEX/_name) for _name in ('generation','evaluation','operations','setup','diagnostics')]+[str(_CODEX)]

import argparse,contextlib,fcntl,hashlib,json,math,subprocess,time
from pathlib import Path
import cv2,requests
from eval_media import RUN,continuity,credentials,data_url,dump,frame
from workspace_paths import PROJECT_ROOT,CONFIG_ROOT,INPUT_ROOT,REFERENCES_ROOT,load_json
from short_drama_protocol import VERSION,METRICS,SCOPES,DISCLOSURES,aggregate,build_jobs,digest,settings,parse_response
from api_throttle import RequestSlot,ProviderUnavailable,cooldown


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def audiovisual(video,start,end,folder,cfg):
    folder.mkdir(parents=True,exist_ok=True)
    times=[start+i/cfg['video_sampling_fps'] for i in range(max(1,math.ceil((end-start)*cfg['video_sampling_fps']-1e-9)))]
    frames=[frame(video,t,folder/('frame_%05d.jpg'%i),cfg['frame_max_width']) for i,t in enumerate(times) if t<end]
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type','-of','json',str(video)],text=True))['streams']
    has_audio=any(x['codec_type']=='audio' for x in streams)
    audio=folder/'audio.wav'
    if has_audio and not audio.exists():
        subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-ss',str(start),'-i',str(video),'-t',str(end-start),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(audio)],check=True,stdin=subprocess.DEVNULL)
    timeline={'start_sec':start,'end_sec':end,'sampling_fps':cfg['video_sampling_fps'],
              'sampling_status':'implementation choice, unspecified for these metrics in paper',
              'frames':frames,'has_audio_stream':has_audio,'audio':str(audio) if has_audio else None,
              'audio_encoding':'WAV mono 16kHz PCM16' if has_audio else None}
    dump(folder/'evidence.json',timeline)
    content=[{'type':'video','video':[data_url(Path(f['path']),'image/jpeg') for f in frames]}]
    if has_audio:content.append({'type':'input_audio','input_audio':{'data':data_url(audio,'audio/wav'),'format':'wav'}})
    return content,timeline


def strict_judge(prompt,content,out,cfg,fingerprint):
    out.mkdir(parents=True,exist_ok=True)
    env=credentials();key=env['DASHSCOPE_API_KEY'];base=env.get('JUDGE_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
    payload={'model':'qwen3.5-omni-plus','messages':[{'role':'user','content':[{'type':'text','text':prompt}]+content}],
             'modalities':['text'],'stream':True,'stream_options':{'include_usage':True},
             'max_tokens':cfg['max_tokens'],'temperature':cfg['temperature']}
    request_sha=digest(payload)
    result_path=out/'result.json'
    if result_path.exists():
        previous=load_json(result_path)
        if previous.get('fingerprint')!=fingerprint or previous.get('payload_sha256')!=request_sha:
            raise RuntimeError('Cache mismatch; refusing to reuse stale score')
        return previous
    dump(out/'request.json',{'model':payload['model'],'endpoint':base,'prompt':prompt,'payload_sha256':request_sha,
         'fingerprint':fingerprint,'media_count':len(content),'temperature':cfg['temperature'],'max_tokens':cfg['max_tokens'],
         'output_contract':'strict JSON object with integer score 1..5 and nonempty analysis'})
    last=''
    for attempt in range(3):
        try:
            with RequestSlot(),requests.post(base+'/chat/completions',headers={'Authorization':'Bearer '+key},json=payload,stream=True,timeout=(30,240)) as response:
                if response.status_code!=200:
                    message=('HTTP %d: '%response.status_code+response.text[:1500]).replace(key,'[REDACTED]')
                    if response.status_code==429:cooldown(message,90);raise ProviderUnavailable(message)
                    raise RuntimeError(message)
                chunks=[];text=''
                for line in response.iter_lines():
                    if not line.startswith(b'data: ') or line==b'data: [DONE]':continue
                    item=json.loads(line[6:]);chunks.append(item)
                    if item.get('error'):raise RuntimeError(str(item['error']))
                    for choice in item.get('choices',[]):text+=choice.get('delta',{}).get('content') or ''
            dump(out/('response_attempt_%d.json'%attempt),{'chunks':chunks,'text':text})
            parsed,normalized=parse_response(text)
            result={'status':'SCORED','model':payload['model'],'score':parsed['score'],'analysis':parsed['analysis'],
                'score_range':[1,5],'markdown_fence_removed':normalized,'attempt':attempt,'fingerprint':fingerprint,'payload_sha256':request_sha,
                'model_response_id':next((x.get('id') for x in chunks if x.get('id')),None)}
            dump(result_path,result);return result
        except Exception as ex:
            last=str(ex).replace(key,'[REDACTED]');dump(out/('error_attempt_%d.json'%attempt),{'error':last})
            if 'HTTP 401' in last or 'HTTP 403' in last:break
            if attempt<2:time.sleep(3*(attempt+1))
    raise RuntimeError(last)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',required=True)
    p.add_argument('--prepare',action='store_true');p.add_argument('--metrics',nargs='+',choices=METRICS)
    a=p.parse_args();cid=a.case
    protocol=load_json(CONFIG_ROOT/'evaluation_protocol.json')['short_drama']
    if protocol.get('status')=='SKIPPED_BY_USER' and not a.prepare:
        raise RuntimeError('Short-Drama-Bench is skipped for this experiment; inspect configuration before enabling it')
    unit_path=CONFIG_ROOT/'evaluation_units.json';units=load_json(unit_path)[cid]
    input_path=INPUT_ROOT/cid;plan=load_json(input_path/'plan.json')
    context=(input_path/'benchmark_prompt.txt').read_text()
    raw_template=(REFERENCES_ROOT/'short_drama_evaluation_template.txt').read_text()
    template=raw_template.split('Metric-specific fields:')[0]
    cfg=settings(protocol.get('alignment_settings'))
    if cfg['continuity_frame_max_width']!=768 or cfg['continuity_spacing']!='consecutive_decoded_frames':
        raise ValueError('Continuity media helper supports the declared consecutive/768px policy only')
    jobs=build_jobs(units,plan['duration_sec'],cfg,protocol.get('not_applicable_by_case',{}).get(cid,{}))
    if a.metrics:jobs=[x for x in jobs if x['metric'] in a.metrics]
    video=RUN/'videos'/(cid+'.mp4')
    if not video.is_file():raise FileNotFoundError(video)
    capture=cv2.VideoCapture(str(video));fps=capture.get(cv2.CAP_PROP_FPS);frames=capture.get(cv2.CAP_PROP_FRAME_COUNT);capture.release()
    actual_duration=frames/fps if fps>0 else 0
    if abs(actual_duration-float(plan['duration_sec']))>max(.15,2/max(fps,1)):
        raise ValueError('Declared timeline differs from actual video duration; annotate before scoring')
    source_files=[Path(__file__),Path(__file__).with_name('short_drama_protocol.py'),Path(__file__).with_name('eval_media.py')]
    clip_paths={x['clip_id']:RUN/'cases'/cid/('shot_%02d.mp4'%x['clip_id']) for x in units['clips']}
    needed={x['previous']['clip_id'] for x in jobs if x['kind']=='continuity' and x.get('status')!='NOT_APPLICABLE'}|{x['next']['clip_id'] for x in jobs if x['kind']=='continuity' and x.get('status')!='NOT_APPLICABLE'}
    fingerprint_data={'version':VERSION,'settings':cfg,'disclosures':DISCLOSURES,'template_sha256':digest(raw_template),
        'rubrics':{m:protocol['rubrics'][m] for m in METRICS},'input_context':context,'scene_boundaries_status':units.get('scene_boundaries_status'),
        'video_sha256':file_hash(video),'clips_sha256':{str(k):file_hash(clip_paths[k]) for k in sorted(needed)},
        'jobs':jobs,'code_sha256':{x.name:file_hash(x) for x in source_files}}
    fingerprint=digest(fingerprint_data)
    base=RUN/'evaluation'/('short_drama_'+VERSION)/cid
    out=base/'runs'/fingerprint[:20];out.mkdir(parents=True,exist_ok=True)
    with (base/'case.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        record={'case_id':cid,'version':VERSION,'fingerprint':fingerprint,'fingerprint_inputs':fingerprint_data,
                'jobs':jobs,'output_dir':str(out),'legacy_results_preserved':str(RUN/'evaluation/short_drama'/cid),
                'paper_scope_and_adaptations':DISCLOSURES,'actual_duration_sec':actual_duration,
                'scene_boundaries_status':units.get('scene_boundaries_status','not declared')}
        dump(out/'plan.json',record);dump(base/'current_plan.json',record)
        if a.prepare:
            print(json.dumps({'status':'PREPARED_NO_API_CALLS','case_id':cid,'planned_units':len(jobs),
                'applicable_units':sum(x.get('status')!='NOT_APPLICABLE' for x in jobs),'plan':str(out/'plan.json')},ensure_ascii=False));return
        results=[];media_cache={}
        for job in jobs:
            metric=job['metric'];unit=job['unit'];jobout=out/metric/unit
            if job.get('status')=='NOT_APPLICABLE':result={'status':'NOT_APPLICABLE','reason':job['reason']}
            else:
                try:
                    if job['kind']=='continuity':
                        key=('pair',job['previous']['clip_id'],job['next']['clip_id'])
                        if key not in media_cache:media_cache[key]=continuity(clip_paths[key[1]],clip_paths[key[2]],out/'evidence'/unit)
                    else:
                        key=('av',job['start_sec'],job['end_sec'])
                        if key not in media_cache:media_cache[key]=audiovisual(video,key[1],key[2],out/'evidence'/digest(key)[:16],cfg)
                    content,evidence=media_cache[key]
                    rubric=protocol['rubrics'][metric]
                    if rubric['scope']!=SCOPES[metric]:raise ValueError('Configured scope disagrees with Figure 10')
                    reference={'benchmark_prompt':context,'declared_unit':job['reference'],'evidence':evidence}
                    prompt=template.replace('{metric}',metric).replace('{scope}',SCOPES[metric]).replace('{rubric}',rubric['rubric']).replace('{context}',json.dumps(reference,ensure_ascii=False))
                    result=strict_judge(prompt,content,jobout,cfg,fingerprint)
                except (Exception,ProviderUnavailable) as ex:
                    result={'status':'FAILED','error':str(ex)};dump(jobout/'failure.json',result)
            results.append(dict(result,metric=metric,unit=unit,case_id=cid))
            print(cid,metric,unit,result.get('score',result.get('reason',result.get('error'))),flush=True)
        summary=aggregate(jobs,results)
        selected=set(a.metrics or METRICS)
        complete=all(summary[m]['status'] in ['SCORED','NOT_APPLICABLE'] for m in selected)
        report={'case_id':cid,'status':'COMPLETE_SELECTED_METRICS' if complete else 'INCOMPLETE',
            'protocol_version':VERSION,'fingerprint':fingerprint,'judge':'qwen3.5-omni-plus','judge_count':1,
            'original_paper_judge_ensemble':protocol['paper_judges'],'adaptations':DISCLOSURES,
            'metrics_selected':sorted(selected),'metrics':{m:summary[m] for m in METRICS if m in selected},'units':results,'plan':str(out/'plan.json')}
        dump(out/'summary.json',report);dump(base/'latest_summary.json',report)
        if not complete:raise RuntimeError('Incomplete scoring; missing/failed units are not averaged as a finished metric')

if __name__=='__main__':main()
