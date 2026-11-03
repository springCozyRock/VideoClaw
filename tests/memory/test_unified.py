import copy
import json
import tempfile
import unittest
from pathlib import Path
from memory import Memory, Segment, Reference, Policy
from memory.assets.store import MemoryStore, ConcurrentSelection
from memory.contracts.errors import PendingAction
from fakes import FakeBackend


class UnifiedTests(unittest.TestCase):
    def setup_case(self, tmp, **kwargs):
        anchor = Path(tmp) / 'anchor.png'
        anchor.write_text('original identity')
        memory = Memory(Path(tmp) / 'run', 'test', Policy(global_references=False,
            frame_candidates=2, video_candidates=2, selection='strict', **kwargs))
        memory.register_story([Segment('s0', 'remove apron', 5, ('Penguin',)),
                               Segment('s1', 'advance', 5, ('Penguin',))],
                              [Reference('anchor', str(anchor), 'Penguin', ('Penguin',))])
        return memory

    def test_aard_schema_sqlite_resume_and_actual_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.setup_case(tmp)
            backend = FakeBackend(continuous=True)
            records = m.generate(backend)
            before = len(backend.calls)
            self.assertEqual(json.loads(json.dumps(m.generate(backend))), json.loads(json.dumps(records)))
            self.assertEqual(len(backend.calls), before)
            snap = m.snapshot()
            self.assertEqual(snap['schema'], 'aard.memory/2')
            self.assertEqual(len(snap['M']), 2)
            self.assertTrue(snap['world_state'])
            self.assertFalse((Path(m.directory) / 'memory.json').exists())
            self.assertTrue(all(set(s['F']) == {'begin', 'end'} for s in snap['M']))
            with MemoryStore(m.directory, 'test') as store:
                assets = {a['id']: a for a in store.journal.all_artifacts()}
            self.assertNotEqual(snap['M'][0]['F']['begin'], snap['M'][0]['generation']['conditions']['condition_frame'])
            self.assertTrue(Path(assets[snap['M'][0]['V']]['path']).exists())

    def test_local_selection_invalidates_then_regenerates_dependants(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.setup_case(tmp, early_stop=10)
            backend = FakeBackend(video_scores=(8, 9, 9, 9), continuous=True)
            m.generate(backend)
            first = m.snapshot()['M'][0]
            old_calls = backend.video_count
            m.select_candidate('s0', 'segment/0/video/0', backend)
            snap = m.snapshot()
            self.assertNotEqual(snap['M'][0]['revision_id'], first['revision_id'])
            self.assertTrue(snap['M'][1]['stale'])
            self.assertEqual(backend.video_count, old_calls)
            m.generate(backend)
            self.assertTrue(all(not s['stale'] for s in m.snapshot()['M']))
            self.assertGreater(backend.video_count, old_calls)

    def test_pending_generation_is_not_resubmitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MemoryStore(tmp, 'test') as store:
                def unknown():
                    raise TimeoutError('unknown provider outcome')
                with self.assertRaises(TimeoutError):
                    store.operation('paid', {'p': 1}, unknown)
                with self.assertRaises(PendingAction):
                    store.operation('paid', {'p': 1}, lambda: self.fail('duplicate call'))

    def test_concurrent_selection_cannot_overwrite_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MemoryStore(tmp, 'test') as a, MemoryStore(tmp, 'test') as b:
                a.save()
                with self.assertRaises(ConcurrentSelection):
                    b.save()

    def test_failed_quality_never_commits_or_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.setup_case(tmp)
            from memory import QualityBlocked
            with self.assertRaises(QualityBlocked):
                m.generate(FakeBackend(bad_video=True, interpolate=True))
            self.assertEqual(m.snapshot()['M'], [])

    def test_publication_replay_does_not_generate(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.setup_case(tmp)
            b = FakeBackend()
            m.generate(b)
            events = m.pending_publications()
            self.assertEqual(len(events), 2)
            m.acknowledge(events[0]['event_id'])
            self.assertEqual(len(m.pending_publications()), 1)

    def test_revised_story_keeps_old_versions_but_excludes_their_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.setup_case(tmp)
            b = FakeBackend()
            m.generate(b)
            refs = m.references
            m.revise_story([Segment('s0', 'new plot', 5, ('Penguin',))], refs)
            self.assertTrue(all(s['stale'] for s in m.snapshot()['M']))
            self.assertFalse(m.snapshot()['world_state'])
            m.generate(b)
            self.assertEqual(len([s for s in m.snapshot()['M'] if not s['stale']]), 1)

    def test_legacy_import_preserves_original_and_requires_explicit_new_generation(self):
        from memory.assets.migration import import_legacy
        from memory import MemoryController
        with tempfile.TemporaryDirectory() as tmp:
            m = self.setup_case(tmp)
            old = Path(tmp) / 'legacy'
            with MemoryStore(old) as store:
                MemoryController(store, FakeBackend(), m.policy).run(m.segments, m.references)
            with MemoryStore(old) as store:
                legacy_fixture = dict(store.data, schema=1)
            (old / 'memory.json').write_text(json.dumps(legacy_fixture))
            before = (old / 'memory.json').read_bytes()
            imported = Path(tmp) / 'imported'
            import_legacy(old / 'memory.json', imported, 'test')
            result = Memory(imported, 'test', m.policy)
            self.assertEqual(len(result.snapshot()['M']), 2)
            self.assertEqual((old / 'memory.json').read_bytes(), before)
            result.register_story(m.segments, m.references)
            with self.assertRaisesRegex(ValueError, 'read-only'):
                result.generate(FakeBackend())

    def test_mutable_observer_never_sees_competing_reference_outfits(self):
        from fakes import offline_backend
        b = offline_backend()
        calls = []
        b.transport.structured = lambda instruction, data, validator, **media: calls.append((data, media)) or {'facts': []}
        b.inspect_state('frame', '/actual.png', [
            {'entity': 'Penguin', 'attribute': 'wearing_apron', 'phase': 'end'},
            {'entity': 'Penguin', 'attribute': 'identity_matches_anchor', 'phase': 'end'}],
            Segment('s', 'not shown to observer', 5),
            [{'entities': ['Penguin'], 'locations': [], 'media': {'path': '/anchor.png'}}])
        self.assertEqual(calls[0][1]['images'], ['/actual.png'])
        self.assertEqual(calls[1][1]['images'], ['/actual.png', '/anchor.png'])
        self.assertNotIn('expected', json.dumps(calls))
