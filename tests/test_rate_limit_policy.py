import ast,contextlib,hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import msvbench_qwen as qwen
import rate_limit_policy as policy

class Response:
    def __init__(self,status=200,text='limit_burst_rate'):
        self.status_code=status;self.text=text
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_lines(self):return [b'data: {"choices":[{"delta":{"content":"ok"}}]}',b'data: [DONE]']

class RateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
    def api(self):
        api=qwen.QwenAPI.__new__(qwen.QwenAPI)
        api.key='test';api.base='https://example.invalid';api.model='test';api.out=self.path;api.retry_delays=()
        return api
    def test_judge_retries_explicit_limit_even_with_generic_retries_disabled(self):
        with patch.object(qwen.requests,'post',side_effect=[Response(429),Response()]) as post,patch.object(qwen.time,'sleep') as sleep:
            self.assertEqual(self.api()._call('test'),'ok');self.assertEqual(post.call_count,2);sleep.assert_called_once_with(5)
    def test_judge_retry_budget_is_bounded(self):
        with patch.object(qwen.requests,'post',return_value=Response(429)) as post,patch.object(qwen.time,'sleep') as sleep:
            with self.assertRaises(RuntimeError):self.api()._call('test')
            self.assertEqual(post.call_count,6);self.assertEqual([c.args for c in sleep.call_args_list],[(5,)]*5)
    def test_uncertain_transport_is_not_retried_when_disabled(self):
        with patch.object(qwen.requests,'post',side_effect=qwen.requests.Timeout('uncertain')) as post,patch.object(qwen.time,'sleep') as sleep:
            with self.assertRaises(RuntimeError):self.api()._call('test')
            self.assertEqual(post.call_count,1);sleep.assert_not_called()
    def test_non_rate_failure_is_not_retried_when_disabled(self):
        with patch.object(qwen.requests,'post',return_value=Response(401,'unauthorized')) as post,patch.object(qwen.time,'sleep') as sleep:
            with self.assertRaises(RuntimeError):self.api()._call('test')
            self.assertEqual(post.call_count,1);sleep.assert_not_called()
    def function(self,name,env):
        tree=ast.parse((ROOT/'scripts/videoclaw_runtime.py').read_text())
        outer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='install_adapters')
        node=next(n for n in outer.body if isinstance(n,ast.FunctionDef) and n.name==name)
        env.update(Path=Path,json=json,hashlib=hashlib,os=os,time=time,ROOT=self.path,RUN=self.path,media_url=lambda p:'data:test',enable_last_frame=True,
          RATE_LIMIT_RETRY_SECONDS=5,MAX_RATE_LIMIT_RETRIES=5,is_rate_limited=policy.is_rate_limited,
          dump=lambda p,v:(p.parent.mkdir(parents=True,exist_ok=True),p.write_text(json.dumps(v))))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'runtime-extracted','exec'),env)
        return env[name]
    def test_video_rate_rejection_retries_at_five_seconds(self):
        response=SimpleNamespace(status_code=429,code='Throttling',message='quota')
        class R(dict):
            status_code=429;code='Throttling';message='quota'
        client=SimpleNamespace(api_key='test',base_url='https://example.invalid')
        from unittest.mock import Mock
        call=Mock(return_value=R())
        fn=self.function('video',{'dashscope':SimpleNamespace(VideoSynthesis=SimpleNamespace(async_call=call))})
        with patch.object(time,'sleep') as sleep:
            with self.assertRaises(RuntimeError):fn(client,'prompt','input.png',str(self.path/'out.mp4'),model='wan3.test')
            self.assertEqual(call.call_count,6);self.assertEqual([c.args for c in sleep.call_args_list],[(5,)]*5)
    def test_image_rejection_then_success(self):
        from unittest.mock import Mock
        rejected=SimpleNamespace(status_code=429,code='limit_burst_rate',message='limited')
        success=SimpleNamespace(status_code=200,output=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=[{'image':'https://example.invalid/image'}]))]))
        call=Mock(side_effect=[rejected,success]);fn=self.function('qwen_image',{'dashscope':SimpleNamespace(MultiModalConversation=SimpleNamespace(call=call))})
        with patch.object(time,'sleep') as sleep:
            self.assertEqual(fn(SimpleNamespace(api_key='test'),'prompt','qwen-image','1*1',1,None,None,[]),['https://example.invalid/image']);sleep.assert_called_once_with(5)
    def test_image_uncertain_submission_not_retried(self):
        from unittest.mock import Mock
        call=Mock(side_effect=TimeoutError('unknown'));fn=self.function('qwen_image',{'dashscope':SimpleNamespace(MultiModalConversation=SimpleNamespace(call=call))})
        with patch.object(time,'sleep') as sleep:
            with self.assertRaises(TimeoutError):fn(SimpleNamespace(api_key='test'),'prompt','qwen-image','1*1',1,None,None,[])
            self.assertEqual(call.call_count,1);sleep.assert_not_called()
    def test_shared_queue_default_is_five_seconds(self):
        import aard_qwen_pacing
        api=self.api();key=hashlib.sha256((api.base+'|'+api.model).encode()).hexdigest();(self.path/(key+'.json')).write_text(json.dumps({'ended_at':100}))
        original=qwen.QwenAPI.request_slot
        try:
            aard_qwen_pacing.install(self.path)
            with patch.object(time,'time',return_value=100),patch.object(time,'sleep') as sleep:
                with api.request_slot():pass
                sleep.assert_called_once_with(5)
            self.assertEqual(json.loads((self.path/(key+'.json')).read_text())['minimum_gap_seconds'],5)
        finally:qwen.QwenAPI.request_slot=original

if __name__=='__main__':unittest.main()
