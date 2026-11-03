"""Offline language routing, English templates, source-speech preservation and call counts."""
import ast
import json
import os
from pathlib import Path
import string
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BACKEND=Path(os.environ.get('VIDEOCLAW_BACKEND',ROOT/'video-claw/video-claw/backend'))
sys.path.insert(0,str(BACKEND))
from prompting.language import (VERSION, resolve_language, project_language, script_text,
    language_instruction, media_prompt, protected_speech, assert_speech_preserved, shot_source)
from prompts.loader import load_prompt
from core.agents.script_agent import ScriptWriterAgent, _get_script_prompt
from core.agents.video_agent import VideoDirectorAgent
from core.agents.character_agent import CharacterDesignerAgent
from core.agents.reference_agent import ReferenceGeneratorAgent
from core.agents.storyboard_agent import StoryboardAgent


class LanguageTests(unittest.TestCase):
    def test_chinese_body_overrides_english_title(self):
        value=resolve_language(script='小林走进房间。',title='Homecoming')
        self.assertEqual((value['story_language'],value['story_language_source']),('zh','script'))

    def test_english_body_overrides_chinese_title(self):
        self.assertEqual(resolve_language(script='Alice enters the room.',title='回家')['story_language'],'en')

    def test_idea_and_title_fallbacks_still_automatic(self):
        self.assertEqual(resolve_language(idea='一个人寻找家人')['story_language'],'zh')
        self.assertEqual(resolve_language(idea='A lost traveler')['story_language'],'en')
        self.assertEqual(resolve_language(title='回家')['story_language_source'],'title')
        self.assertEqual(resolve_language()['story_language_source'],'default')

    def test_explicit_override(self):
        self.assertEqual(resolve_language('en',script='中文故事')['story_language'],'en')
        with self.assertRaises(ValueError):resolve_language('fr')

    def test_project_reads_script_before_idea(self):
        art={'script_generation':{'title':'An English Title','meta':{'original_text':'甲：“你终于回来了。”'},'episodes':[]}}
        value=project_language({'idea':'An English seed'},art)
        self.assertEqual(value['story_language'],'zh')
        self.assertEqual(value['story_language_source'],'script')

    def test_saved_language_and_provenance_survive_title_changes(self):
        values={'story_language':'zh','story_language_source':'script'}
        self.assertEqual(project_language(values,{'script_generation':{'title':'Title'}})['story_language_source'],'script')

    def test_language_header_is_english_even_for_chinese_story(self):
        text=language_instruction('zh')
        self.assertIn('story language is Chinese',text)
        self.assertFalse(any('\u4e00'<=c<='\u9fff' for c in text))
        self.assertIn('copy them verbatim',text)

    def test_media_policy_does_not_translate_or_call_a_model(self):
        source='Medium shot. 小林：“你终于回来了。”\n旁白：那天，他回到了家。'
        prompt=media_prompt(source,'zh')
        self.assertTrue(prompt.endswith(source))
        self.assertEqual(media_prompt(prompt,'zh'),prompt)
        module=ast.parse((ROOT/'prompting/language.py').read_text())
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in ('query','generate','generate_multimodal') for n in ast.walk(module)))

    def test_protected_speech_includes_narration_and_named_speakers(self):
        source='小林：你终于回来了。\n旁白：那天，他回到了家。'
        self.assertIn('你终于回来了。',protected_speech(source))
        self.assertIn('那天，他回到了家。',protected_speech(source))
        with self.assertRaises(ValueError):assert_speech_preserved(source,'You came back.')
        assert_speech_preserved(source,source)

    def test_new_and_legacy_shot_markers_exclude_biographies(self):
        for marker in ('Shot list:', '分镜列表：','分镜列表:'):
            self.assertEqual(shot_source('Characters: old costume\n'+marker+'\nremove apron'),'remove apron')

    def test_english_template_missing_does_not_fallback_to_chinese(self):
        with self.assertRaises(FileNotFoundError):load_prompt('script','does_not_exist','en')

    def test_all_active_english_templates_format_and_keep_schema(self):
        folder=BACKEND/'prompts'
        for category in ('script','storyboard','character','setting','reference','doctor','pipelines'):
            names={p.name[:-7] for p in (folder/category).glob('*_zh.txt')}
            for name in names:
                with self.subTest(category=category,name=name):
                    text=load_prompt(category,name,'en')
                    fields={field for _,field,_,_ in string.Formatter().parse(text) if field}
                    text.format(**{field:'TEST' for field in fields})
                    self.assertIn('@en-v2',text)

    def test_script_template_language_is_independent_of_story(self):
        self.assertIn('@en-v2',_get_script_prompt('generate_script','zh'))
        self.assertIn('@en-v2',_get_script_prompt('generate_script','en'))
        self.assertIn('core inspiration',_get_script_prompt('generate_script','zh'))

    def test_character_and_setting_use_english_instructions_with_original_names(self):
        text=CharacterDesignerAgent._char_prompt('小林','穿着红色外套','realistic')
        self.assertIn('Character design',text);self.assertIn('小林',text)
        self.assertIn('Panoramic',CharacterDesignerAgent._setting_prompt('厨房','白色墙面','realistic'))

    def test_one_text_call_preserves_unicode_punctuation(self):
        agent=ScriptWriterAgent();agent._merge_session_params({'idea':'中文故事'})
        llm=Mock();llm.query.return_value='小林：“你终于回来了。”'
        with patch('core.prompt_language.record_prompt') as trace:
            result=agent._cancellable_query(llm,'Write the script.','', 'fake',True)
        self.assertEqual(result,'小林：“你终于回来了。”')
        llm.query.assert_called_once()
        self.assertFalse(llm.query.call_args.args[3])
        self.assertIn('story language is Chinese',llm.query.call_args.args[0])
        trace.assert_called_once()

    def test_one_image_call_no_compiler_request(self):
        agent=ReferenceGeneratorAgent();client=Mock();client.generate_image.return_value=['image.png']
        source='Draw a static image. Character name: 小林.'
        with patch('core.prompt_language.record_prompt'):
            result=agent._generate_image_with_doctor(client,prompt=source,model='fake',llm_model='fake',context={'story_language':'zh'})
        client.generate_image.assert_called_once()
        self.assertIn(source,client.generate_image.call_args.kwargs['prompt'])
        self.assertEqual(result[1],client.generate_image.call_args.kwargs['prompt'])

    def test_video_uses_paired_visual_without_translating_dialogue(self):
        agent=VideoDirectorAgent()
        segment={'shots':[{'duration':5,'content':'小林：“你终于回来了。”','visual_prompt':'Medium shot. 小林：“你终于回来了。”'}]}
        import hashlib
        segment['shots'][0]['visual_prompt_source_hash']=hashlib.sha256(segment['shots'][0]['content'].encode()).hexdigest()
        text=agent._format_shot_section(segment)
        self.assertIn('Medium shot',text);self.assertIn('你终于回来了。',text)
        segment['shots'][0]['visual_prompt']='Medium shot. You came back.'
        self.assertIn('你终于回来了。',agent._format_shot_section(segment))

    def test_storyboard_normalizer_keeps_source_and_english_directions(self):
        plan={'segment_number':1,'items':[{'unit_id':'U001','duration':5}],'characters':['小林'],'location':'门口'}
        raw={'shots':[{'unit_id':'U001','shot_type':'中景','duration':5,'content':'小林：“你好。”','visual_prompt':'Medium shot. 小林：“你好。”'}]}
        result=StoryboardAgent._normalize_segment_design(1,plan,raw)
        self.assertEqual(result['shots'][0]['visual_prompt'],raw['shots'][0]['visual_prompt'])
        self.assertIn('你好。',result['shots'][0]['content'])

    def test_engine_resolves_once_and_saves(self):
        from core.orchestrator import WorkflowEngine,WorkflowState
        import threading
        engine=WorkflowEngine.__new__(WorkflowEngine);engine._state_lock=threading.RLock()
        state=WorkflowState('lang');state.meta={'idea':'English idea'}
        state.artifacts={'script_generation':{'title':'Title','episodes':[{'content':'中文故事正文'}]}}
        engine.get_or_create_state=lambda sid:state
        engine.save_session_to_disk=Mock()
        _,first=engine.prepare_stage_execution('lang','storyboard',{})
        self.assertEqual(first['story_language'],'zh')
        state.artifacts['script_generation']['episodes'][0]['content']='English changed text'
        _,second=engine.prepare_stage_execution('lang','video_generation',{})
        self.assertEqual(second['story_language'],'zh')
        engine.save_session_to_disk.assert_called_once()

    def test_new_session_persists_resolved_language_not_auto(self):
        from core.orchestrator import WorkflowEngine
        with tempfile.TemporaryDirectory() as directory, patch.object(WorkflowEngine, '_load_sessions_from_disk'):
            engine=WorkflowEngine();engine._session_dir=directory
            value=engine.create_session('language',{'idea':'一个中文故事','story_language':'auto'})
            self.assertEqual(value['meta']['story_language'],'zh')
            saved=json.loads((Path(directory)/'language.json').read_text())
            self.assertEqual(saved['meta']['story_language'],'zh')


if __name__=='__main__':unittest.main()
