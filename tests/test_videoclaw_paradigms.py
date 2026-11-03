"""Offline contract/integration tests; models are mocked, no paid requests."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(os.environ.get('VIDEOCLAW_BACKEND', Path(__file__).resolve().parents[1] / 'video-claw/video-claw/backend'))
sys.path.insert(0, str(BACKEND))
from core.generation_paradigms import (
    MODES, conditioning, frame_prompt, grid_groups, resolve_paradigm,
    selected_references, slice_grid, validate_model,
)
from core.agents.reference_agent import ReferenceGeneratorAgent
from core.agents.video_agent import VideoDirectorAgent
from core.agents.paradigm_reference import prepare_references
from PIL import Image


class ParadigmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, self.cwd)
        Image.new('RGB', (128, 72), 'red').save('character.png')
        self.character = str(Path('character.png').absolute())
        self.segments = [dict(segment_id=f'seg_001_0{i}', episode_number=1, segment_number=i,
                              characters=['Alice'], location='', total_duration=5,
                              shots=[{'shot_id':f'shot_{i}', 'content':f'Alice raises her hand {i}'}]) for i in range(1, 4)]
        self.assets = {'characters':[{'id':'alice', 'name':'Alice', 'selected':self.character}]}
        self.artifacts = {'storyboard':{'episodes':[{'episode_number':1,'segments':self.segments}]},
                          'character_design':self.assets}
        self.calls = []

    def data(self, paradigm):
        return {'session_id':'test', 'generation_paradigm':paradigm,
                'style':'realistic', 'video_ratio':'16:9', 'video_resolution':'720P',
                'image_t2i_model':'fake', 'image_it2i_model':'fake',
                'video_model':'wan2.7-r2v' if paradigm=='multiref2v' else 'wan2.7-i2v',
                '_session_meta':{}, '_session_artifacts':copy.deepcopy(self.artifacts)}

    def render(self, client, **kwargs):
        self.calls.append(kwargs)
        directory=Path(kwargs['save_dir']);directory.mkdir(parents=True,exist_ok=True)
        path=directory/f'{len(self.calls)}.png'
        image=Image.new('RGB',(128,72),'red')
        if '2x2' in kwargs['prompt']:
            for color,box in [('green',(64,0,128,36)),('blue',(0,36,64,72)),('yellow',(64,36,128,72))]:
                image.paste(color,box)
        image.save(path)
        return [str(path.absolute())],kwargs['prompt'],None

    def prepare(self, paradigm, data=None, intervention=None):
        agent=ReferenceGeneratorAgent()
        with patch('models.image_client.ImageClient'), patch.object(agent, '_evaluate_with_vlm', return_value={'is_acceptable':True, 'score':9}), patch.object(agent,'_generate_image_with_doctor', side_effect=self.render):
            return asyncio.run(prepare_references(agent,data or self.data(paradigm),intervention))['payload']

    def test_aliases_and_explicit_request_precedence(self):
        for alias,expected in [('first_frame','keyframe2v'),('start_end_frame','fflf2v'),('reference','multiref2v')]:
            self.assertEqual(resolve_paradigm({'video_generation_mode':alias}),expected)
        self.assertEqual(resolve_paradigm({'video_generation_mode':'grid2v'},{'generation_paradigm':'fflf2v'}),'grid2v')
        with self.assertRaises(ValueError):resolve_paradigm({'generation_paradigm':'typo'})

    def test_only_implemented_model_features_allowed(self):
        validate_model('wan2.7-i2v','start_end_frame',5)
        with self.assertRaises(ValueError):validate_model('wan2.7-r2v','first_frame')
        with self.assertRaises(ValueError):validate_model('unknown','start_end_frame')
        with self.assertRaises(ValueError):validate_model('wan2.7-i2v','first_frame',100)

    def test_missing_named_prop_is_not_silently_dropped(self):
        seg={**self.segments[0],'elements':['key']}
        with self.assertRaisesRegex(ValueError,'key'):selected_references(seg,self.assets)
        self.assets['elements']=[{'id':'key','name':'key','selected':self.character}]
        self.assertTrue(selected_references(seg,self.assets))

    def test_grid_groups_never_cross_episode(self):
        episodes=[{'segments':self.segments},{'segments':self.segments[:1]}]
        self.assertEqual([len(x) for x in grid_groups(episodes)],[3,1])

    def test_fflf_uses_own_end_state_and_six_images(self):
        payload=self.prepare('fflf2v')
        self.assertEqual(len(self.calls),6)
        for record in payload['scenes']:
            first,last,refs=conditioning(record,'fflf2v')
            self.assertNotEqual(first,last)
            self.assertIn('final state AFTER',record['last_frame_prompt'])
            self.assertIn(first,self.calls[2*record['index']-1]['image_paths'])
        with self.assertRaises(ValueError):conditioning({**payload['scenes'][0],'last_frame':None},'fflf2v')

    def test_keyframe_independent_generation(self):
        payload=self.prepare('keyframe2v')
        self.assertEqual(len(self.calls),3)
        self.assertEqual(len({r['selected'] for r in payload['scenes']}),3)
        self.assertTrue(all('last_frame' not in r for r in payload['scenes']))

    def test_grid_joint_generation_and_pixel_mapping(self):
        payload=self.prepare('grid2v')
        self.assertEqual(len(self.calls),1)
        self.assertEqual([r['grid_cell'] for r in payload['scenes']],[0,1,2])
        expected=[(255,0,0),(0,128,0),(0,0,255)]
        for record,color in zip(payload['scenes'],expected):
            with Image.open(record['selected']) as image:
                self.assertEqual(image.size,(64,36))
                self.assertEqual(image.getpixel((1,1)),color)

    def test_multiref_has_no_frame_or_image_generation(self):
        payload=self.prepare('multiref2v')
        self.assertEqual(self.calls,[])
        for record in payload['scenes']:
            first,last,refs=conditioning(record,'multiref2v')
            self.assertIsNone(first);self.assertIsNone(last);self.assertEqual(refs,[self.character])

    def test_resume_reuses_complete_group(self):
        first=self.prepare('grid2v');second=self.prepare('grid2v')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(first['scenes'],second['scenes'])

    def test_grid_regeneration_updates_whole_group(self):
        first=self.prepare('grid2v')
        data=self.data('grid2v');data['_session_artifacts']['reference_generation']=first
        second=self.prepare('grid2v',data,{'regenerate_scenes':['seg_001_02']})
        self.assertEqual(len(self.calls),2)
        for old,new in zip(first['scenes'],second['scenes']):
            self.assertNotEqual(old['selected'],new['selected'])
            self.assertEqual(len(new['versions']),2)

    def test_story_and_reference_changes_invalidate_cache(self):
        first=self.prepare('keyframe2v')
        self.segments[0]['shots'][0]['content']='Alice sits down'
        second=self.prepare('keyframe2v')
        self.assertEqual(len(self.calls),4)
        self.assertNotEqual(first['scenes'][0]['source_hash'],second['scenes'][0]['source_hash'])
        Image.new('RGB',(128,72),'blue').save(self.character)
        self.prepare('keyframe2v');self.assertEqual(len(self.calls),7)

    def test_paradigm_mismatch_rejected(self):
        record=self.prepare('keyframe2v')['scenes'][0]
        with self.assertRaises(ValueError):conditioning(record,'grid2v')

    def test_actual_reference_agent_dispatch(self):
        agent=ReferenceGeneratorAgent()
        with patch('models.image_client.ImageClient'), patch.object(agent, '_evaluate_with_vlm', return_value={'is_acceptable':True, 'score':9}),patch.object(agent,'_generate_image_with_doctor',side_effect=self.render):
            result=asyncio.run(agent.process(self.data('grid2v')))
        self.assertEqual(result['payload']['generation_paradigm'],'grid2v')

    def test_video_dispatch_resume_and_stale_failure(self):
        for paradigm in MODES:
            with self.subTest(paradigm=paradigm):
                data=self.data(paradigm);data['session_id']=paradigm
                data['_session_artifacts']['reference_generation']=self.prepare(paradigm)
                agent=VideoDirectorAgent();calls=[]
                def generate(sid,key,prompt,image,model,duration,*args):
                    calls.append((image,args))
                    path=Path(agent._next_version_path(sid,key));path.write_bytes(b'fake-video')
                    return key,str(path.absolute()),None
                with patch.object(agent,'_generate_one',side_effect=generate):
                    result=asyncio.run(agent.process(data))
                    self.assertEqual(len(calls),3)
                    self.assertTrue(all(c['generation_paradigm']==paradigm for c in result['payload']['clips']))
                    asyncio.run(agent.process(data));self.assertEqual(len(calls),3)
                data['video_resolution']='1080P'
                with patch.object(agent,'_generate_one',return_value=('x',None,None)):
                    failed=asyncio.run(agent.process(data))
                self.assertTrue(all(not c['selected'] and c['status']=='failed' for c in failed['payload']['clips']))
                self.assertEqual(calls[0][0] is None,paradigm=='multiref2v')
                if paradigm=='fflf2v':self.assertTrue(calls[0][1][5])

    def test_missing_tail_fails_before_any_video_request(self):
        data=self.data('fflf2v');ref=self.prepare('fflf2v');ref['scenes'][0].pop('last_frame')
        data['_session_artifacts']['reference_generation']=ref
        agent=VideoDirectorAgent()
        with patch.object(agent,'_generate_one') as call:
            with self.assertRaises(ValueError):asyncio.run(agent.process(data))
            call.assert_not_called()

    def make_engine(self):
        import threading
        from core.orchestrator import WorkflowEngine, WorkflowState
        engine=WorkflowEngine.__new__(WorkflowEngine)
        engine._state_lock=threading.RLock();engine._active_sessions=set()
        state=WorkflowState('offline')
        engine.get_state=lambda sid:state
        engine.save_session_to_disk=lambda sid:None
        return engine,state

    def test_multiref_stage_completes_without_selected_frame(self):
        engine,state=self.make_engine()
        state.artifacts['reference_generation']=self.prepare('multiref2v')
        engine._recalculate_all_statuses(state)
        self.assertEqual(state.status['reference_generation'],'completed')

    def test_mode_change_invalidates_downstream_but_preserves_story(self):
        engine,state=self.make_engine()
        state.meta={'video_generation_mode':'keyframe2v'}
        state.artifacts={**self.artifacts,'reference_generation':{},'video_generation':{},'post_production':{}}
        engine.update_session_meta('offline',{'video_generation_mode':'grid2v'},('video_generation_mode',))
        self.assertEqual(state.meta['video_generation_mode'],'grid2v')
        self.assertIn('storyboard',state.artifacts)
        self.assertNotIn('reference_generation',state.artifacts)
        self.assertNotIn('video_generation',state.artifacts)

    def test_invalid_and_running_changes_leave_state_unchanged(self):
        engine,state=self.make_engine();state.meta={'video_generation_mode':'keyframe2v'}
        with self.assertRaises(ValueError):engine.update_session_meta('offline',{'video_generation_mode':'typo'},('video_generation_mode',))
        self.assertEqual(state.meta['video_generation_mode'],'keyframe2v')
        engine._active_sessions.add('offline')
        with self.assertRaises(ValueError):engine.update_session_meta('offline',{'video_generation_mode':'grid2v'},('video_generation_mode',))
        self.assertEqual(state.meta['video_generation_mode'],'keyframe2v')

    def test_model_picker_only_lists_implemented_features(self):
        from models.config_model import list_api_models
        for record in list_api_models('video',['start_end_frame_i2v']):
            self.assertIn('start_end_frame_i2v',record['adapter_ability_types'])

    def test_changed_story_requires_new_reference_preparation(self):
        data=self.data('keyframe2v');data['_session_artifacts']['reference_generation']=self.prepare('keyframe2v')
        data['_session_artifacts']['storyboard']['episodes'][0]['segments'][0]['shots'][0]['content']='changed'
        agent=VideoDirectorAgent()
        with patch.object(agent,'_generate_one') as call:
            with self.assertRaisesRegex(ValueError,'Storyboard changed'):asyncio.run(agent.process(data))
            call.assert_not_called()

    def test_explicit_frame_version_selection_survives_resume(self):
        first=self.prepare('keyframe2v');data=self.data('keyframe2v');data['_session_artifacts']['reference_generation']=first
        second=self.prepare('keyframe2v',data,{'regenerate_scenes':['seg_001_01']})
        data['_session_artifacts']['reference_generation']=second
        chosen=self.prepare('keyframe2v',data,{'selected_images':{'seg_001_01':first['scenes'][0]['selected']}})
        data['_session_artifacts']['reference_generation']=chosen
        resumed=self.prepare('keyframe2v',data)
        self.assertEqual(resumed['scenes'][0]['selected'],first['scenes'][0]['selected'])

    def test_missing_end_frame_keeps_stage_waiting(self):
        engine,state=self.make_engine();ref=self.prepare('fflf2v');ref['scenes'][0].pop('last_frame')
        state.artifacts['reference_generation']=ref
        engine._recalculate_all_statuses(state)
        self.assertEqual(state.status['reference_generation'],'waiting')

    def test_rejected_frame_has_bounded_retry_and_no_success_manifest(self):
        agent=ReferenceGeneratorAgent()
        with patch('models.image_client.ImageClient'), patch.object(agent,'_generate_image_with_doctor',side_effect=self.render), patch.object(agent,'_evaluate_with_vlm',return_value={'score':1,'issues':['wrong person'],'hard_failures':['identity']}):
            with self.assertRaisesRegex(RuntimeError,'failed VLM validation'):
                asyncio.run(prepare_references(agent,self.data('keyframe2v')))
        self.assertEqual(len(self.calls),3)
        self.assertEqual(list(Path('code').rglob('manifest.json')),[])


if __name__=='__main__':unittest.main()
