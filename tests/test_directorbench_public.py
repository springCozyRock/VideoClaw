"""Offline alignment tests: public records, identities, profiles and native graph wiring."""
import copy,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import directorbench_public as db
class AlignmentTests(unittest.TestCase):
 def test_strict_parser_accepts_public_containers(self):
  expected=[{'a':1},{'b':2}]
  for text in ['{"a":1}\n{"b":2}','{\n"a":1\n},\n{"b":2}',json.dumps(expected)]:self.assertEqual(db.parse_objects(text),expected)
 def test_strict_parser_rejects_corruption(self):
  for text in ['{"a":1} junk {"b":2}','{"a":1},','{"a":1},, {"b":2}','42','[{"a":1},null]']:
   with self.subTest(text=text),self.assertRaises((ValueError,json.JSONDecodeError)):db.parse_objects(text)
 def test_raw_files_unchanged_and_every_case_hash_matches(self):
  m=db.verify_files();self.assertEqual(m['counts'],{'original':75,'cross_lingual':134,'multilingual':219})
  self.assertEqual(m['evaluation_pairs'],2996)
 def test_variants_have_unique_keys_and_join_by_sample_id(self):
  entries=db.cases();self.assertEqual(len(entries),428)
  self.assertEqual(entries['cross_lingual/DB_001_content_en']['meta_id'],entries['original/DB_001']['meta_id'])
  self.assertNotEqual(entries['cross_lingual/DB_001_content_en']['case_key'],entries['multilingual/DB_001_instr_en']['case_key'])
 def test_profile_alias_is_explicit_and_preserves_raw(self):
  raw=db.parse_objects((db.DATA/'raw/profiles.jsonl').read_text());before=copy.deepcopy(raw[3]);normal,changes=db.normalize_profile(raw[3])
  self.assertEqual(raw[3],before);self.assertEqual(normal['personalization']['user_taste']['wants_lip_sync'],True)
  self.assertEqual(normal['personalization']['priority_weights'],before['personalization']['priority_weights']);self.assertTrue(changes)
 def test_partial_annotation_not_expanded(self):
  row=db.cases()['original/DB_001'];metadata=db.load(db.ROOT/row['metadata_path'])
  self.assertEqual(row['target_duration_sec'],67);self.assertEqual(row['published_script_duration_sec'],18)
  self.assertEqual(len(metadata['modality_details']['text']['script']),1);self.assertIn('SCRIPT_DURATION_DIFFERS_FROM_TARGET',row['annotation_warnings'])
 def test_missing_duration_is_preserved(self):
  row=db.cases()['original/DB_008'];self.assertIsNone(row['target_duration_sec'])
  self.assertIsNone(db.load(db.ROOT/row['metadata_path'])['duration_sec']);self.assertIn('TARGET_DURATION_NOT_PUBLISHED',row['annotation_warnings'])
 def test_qwen_transport_caches_success_and_redacts_credentials(self):
  import tempfile
  from directorbench_public_provider import QwenProvider
  from directorbench.config import EvalConfig
  class Response:
   status_code=200
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def iter_lines(self):
    yield b'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}],"usage":{"total_tokens":1}}'
    yield b'data: [DONE]'
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'.env').write_text('DASHSCOPE_API_KEY=unit-test-key\n')
   provider=QwenProvider(root,root/'output',EvalConfig())
   with patch('directorbench_public_provider.requests.post',return_value=Response()) as post:
    first=provider.create(messages=[{'role':'user','content':'Return JSON'}],response_format={'type':'json_object'},temperature=.1,max_tokens=100)
    second=provider.create(messages=[{'role':'user','content':'Return JSON'}],response_format={'type':'json_object'},temperature=.1,max_tokens=100)
   self.assertEqual(first.choices[0].message.content,'{}');self.assertEqual(second.choices[0].message.content,'{}');self.assertEqual(post.call_count,1)
   for path in (root/'output').rglob('*.json'):self.assertNotIn('unit-test-key',path.read_text())
 def test_every_public_profile_round_trips(self):
  db.public_imports();from directorbench.schemas import UserProfile
  p=db.profiles();self.assertEqual(set(p),set(range(1,8)))
  for raw in p.values():
   obj=UserProfile.from_profile_dict(raw);self.assertEqual(obj.priority_weights.model_dump(),raw['personalization']['priority_weights'])
  self.assertTrue(UserProfile.from_profile_dict(p[4]).user_taste.wants_lip_sync)
 def test_native_registry_is_version_aligned(self):
  db.public_imports();from directorbench.checkpoints import CHECKPOINTS
  r=db.load(db.CONFIG/'checkpoint_registry.json');self.assertEqual(r['registered_metric_count'],9);self.assertEqual(r['checkpoint_count'],40)
  self.assertEqual(r['registered_metrics'],{k:[x.model_dump(mode='json') for x in v] for k,v in CHECKPOINTS.items()})
 def test_native_graph_compiles_without_network(self):
  db.public_imports();from directorbench.config import EvalConfig
  from directorbench.graph import build_eval_graph
  def forbidden(*a,**kw):raise AssertionError('Network call during offline graph validation')
  client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=forbidden)))
  with patch('directorbench.llm_utils._build_client',return_value=(client,'OFFLINE_VALIDATION',False)),patch('requests.sessions.Session.request',side_effect=forbidden):
   graph=build_eval_graph(EvalConfig());self.assertIn('diagnosis',graph.get_graph().nodes)
 def test_bindings_distinguish_methods_and_refuse_overwrite(self):
  import tempfile,contextlib,io
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);one=folder/'one.mp4';two=folder/'two.mp4';one.write_bytes(b'fixture-one');two.write_bytes(b'fixture-two')
   probe=json.dumps({'streams':[{'codec_type':'video'}],'format':{'duration':'2.0'}})
   with patch.object(db,'CONFIG',folder),patch.object(db,'verify_files',return_value={}),patch.object(db,'cases',return_value={'original/DB_001':{'case_key':'original/DB_001','target_duration_sec':67}}),patch.object(db.subprocess,'check_output',return_value=probe),contextlib.redirect_stdout(io.StringIO()):
    args=SimpleNamespace(case='original/DB_001',method='baseline_a',video=one,generation_profile=None,generation_prompt=None)
    db.bind(args);args.method='baseline_b';args.video=two;db.bind(args)
    self.assertEqual(set(db.bindings()),{'baseline_a::original/DB_001','baseline_b::original/DB_001'})
    args.method='baseline_a'
    with self.assertRaises(RuntimeError):db.bind(args)
 def test_dry_plan_never_needs_video_or_api(self):
  args=SimpleNamespace(case='original/DB_001',profile=4,reference_mode='reference-free',command='run')
  from unittest.mock import patch
  with patch('requests.sessions.Session.request',side_effect=AssertionError('No API calls')):
   item=db.plan(args)
  self.assertEqual(item['status'],'WAITING_FOR_VIDEO');self.assertIsNone(item['script_text_path']);self.assertEqual(item['profile']['profile_id'],4)
if __name__=='__main__':unittest.main(verbosity=2)
