import unittest
from short_drama_protocol import build_jobs,aggregate,settings,parse_response

class ProtocolRegression(unittest.TestCase):
    def setUp(self):
        self.units={'scenes':[{'scene_id':1,'start_sec':0,'end_sec':30}, {'scene_id':2,'start_sec':30,'end_sec':60}],
                    'clips':[{'clip_id':1,'start_sec':0,'end_sec':15},{'clip_id':2,'start_sec':15,'end_sec':30},{'clip_id':3,'start_sec':30,'end_sec':60}]}
    def test_scope_windows_do_not_expand_to_entire_scenes(self):
        jobs=build_jobs(self.units,60)
        pick=lambda m:[(j['start_sec'],j['end_sec']) for j in jobs if j['metric']==m]
        self.assertEqual(pick('opening_hook'),[(0,10)])
        self.assertEqual(pick('narrative_coherence'),[(0,60)])
        self.assertEqual(pick('end_hook'),[(20,30),(50,60)])
        self.assertEqual(pick('escalation_effect'),[(10,20),(40,50)])
        self.assertEqual(pick('transition_naturalness'),[(25,35)])
    def test_short_scene_and_full_transition_are_kept(self):
        u={'scenes':[{'scene_id':1,'start_sec':0,'end_sec':4},{'scene_id':2,'start_sec':4,'end_sec':8}],
           'clips':[{'clip_id':1,'start_sec':0,'end_sec':4},{'clip_id':2,'start_sec':4,'end_sec':8}],
           'transitions':[{'before_scene_id':1,'after_scene_id':2,'start_sec':3,'end_sec':5}]}
        jobs=build_jobs(u,8,{'transition_tail_seconds':1,'transition_head_seconds':1})
        transition=next(x for x in jobs if x['metric']=='transition_naturalness')
        self.assertEqual((transition['start_sec'],transition['end_sec']),(2,6))
        self.assertTrue(all(x['end_sec']>x['start_sec'] for x in jobs if x['kind']=='audiovisual'))
    def test_exclusion_happens_before_scoring_and_partial_is_not_complete(self):
        jobs=build_jobs(self.units,60,na_reasons={'character_spatial_continuity':'NO_CHARACTERS'})
        self.assertTrue(all(x.get('status')=='NOT_APPLICABLE' for x in jobs if x['metric']=='character_spatial_continuity'))
        report=aggregate(jobs,[{'metric':'end_hook','status':'SCORED','score':4}])
        self.assertIsNone(report['end_hook']['score']);self.assertEqual(report['end_hook']['status'],'INCOMPLETE')
        self.assertEqual(report['character_spatial_continuity']['status'],'NOT_APPLICABLE')
    def test_response_format_does_not_accept_loose_or_invalid_scores(self):
        valid='{"score": 4, "analysis": "Visible evidence"}'
        self.assertEqual(parse_response(valid)[0]['score'],4)
        self.assertTrue(parse_response('```json\n'+valid+'\n```')[1])
        for bad in ['Score: 4','{"score": true, "analysis": "x"}','{"score": 5.0, "analysis": "x"}','{"score": 6, "analysis": "x"}','{"score": 4, "analysis": ""}']:
            with self.assertRaises(ValueError):parse_response(bad)
    def test_bad_timeline_and_changed_paper_constants_fail(self):
        self.units['scenes'][1]['start_sec']=31
        with self.assertRaises(ValueError):build_jobs(self.units,60)
        with self.assertRaises(ValueError):settings({'opening_seconds':12})
        with self.assertRaises(ValueError):settings({'continuity_frames_per_side':2})

if __name__=='__main__':unittest.main()
