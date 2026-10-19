"""Behavior and data-integrity tests. Run: python -m unittest discover -s tests -v."""
import io
import json
import sqlite3
import struct
import sys
import tempfile
import types
import unittest
import wave
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import create_app
from agreement import calculate_agreement


def wav_bytes(frequency=0):
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(struct.pack('<h', frequency) * 8000)
    return out.getvalue()


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent / '.scratch'
        scratch.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=scratch)
        self.app = create_app({'TESTING': True, 'DATA_DIR': self.folder.name, 'PASS2_DELAY_MINUTES': 60, 'GEMINI_API_KEY': ''})
        self.client = self.app.test_client()
        self.headers = {'X-Workspace': 'study'}

    def tearDown(self):
        assert Path(self.folder.name).resolve().is_relative_to(Path(__file__).resolve().parent / '.scratch')
        self.folder.cleanup()

    def get(self, path):
        return self.client.get('/api' + path, headers=self.headers)

    def post(self, path, data=None):
        return self.client.post('/api' + path, json=data or {}, headers=self.headers)

    def add(self, sample=0):
        response = self.client.post('/api/clips', data={'title': f'Test clip {sample}', 'duration_s': '1',
            'source_url': 'Original work', 'licence': 'CC0', 'attribution': 'Test fixture',
            'file': (io.BytesIO(wav_bytes(sample)), 'test.wav')}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['id']

    def annotate(self, cid, p=1, label='Safe', **overrides):
        data = {'clip_id': cid, 'pass': p, 'label': label, 'rule_id': 'R6', 'rationale': 'A quiet test tone is audible with no speech.', 'flagged': False, 'segments': []}
        data.update(overrides)
        return self.post('/annotate', data)

    def unlock_wait(self):
        with closing(sqlite3.connect(self.app.config['DATABASE'])) as db, db:
            db.execute("UPDATE studies SET pass2_available_at=? WHERE id=?", ((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),self.headers['X-Workspace']))

    def finish(self, different=False):
        cid = self.add()
        self.assertEqual(self.annotate(cid).status_code, 201)
        self.assertEqual(self.post('/lock-pass1').status_code, 200)
        self.unlock_wait()
        self.assertEqual(self.post('/start-pass2').status_code, 200)
        self.assertEqual(self.annotate(cid, 2, 'Needs review' if different else 'Safe').status_code, 201)
        return cid

    def test_blank_study_has_no_invented_results(self):
        state = self.get('/state').json
        self.assertEqual(state['total'], 0)
        self.assertEqual(state['pass1_count'], 0)
        self.assertEqual(self.get('/agreement').status_code, 423)
        self.assertIsNone(self.get('/comparison').json['within_one_pct'])

    def test_upload_tracks_provenance_and_rejects_duplicates(self):
        cid = self.add()
        clip = self.get('/clips').json[0]
        self.assertEqual(clip['licence'], 'CC0')
        self.assertEqual(clip['attribution'], 'Test fixture')
        self.assertNotIn('media_path', clip)
        response = self.client.post('/api/clips', data={'title': 'Duplicate', 'duration_s': '1', 'source_url': 'Original work', 'licence': 'CC0', 'attribution': 'Test', 'file': (io.BytesIO(wav_bytes()), 'duplicate.wav')}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        media = self.client.get(f'/media/{cid}', headers={'Range': 'bytes=0-9'})
        self.assertEqual(media.status_code, 206)
        self.assertEqual(len(media.data), 10)
        media.close()

    def test_rules_rationale_flags_and_segments_are_validated(self):
        cid = self.add()
        for override in [{'rule_id': ''}, {'rationale': ''}, {'label': 'Unknown'}, {'pass': True},
                         {'flagged': True, 'flag_ts': 9}, {'flagged': 'false'},
                         {'rule_id':'R8','label':'Needs review','flagged':False},
                         {'segments':[{'start_s':.9,'end_s':.1,'label':'Safe'}]},
                         {'segments':[{'start_s':0,'end_s':2,'label':'Safe'}]},
                         {'segments':[{'start_s':0,'end_s':float('nan'),'label':'Safe'}]}]:
            self.assertEqual(self.annotate(cid, **override).status_code, 400, override)
        valid = self.annotate(cid, flagged=True, flag_ts=.5, segments=[{'start_s':.1,'end_s':.9,'label':'Safe'}])
        self.assertEqual(valid.status_code, 201)
        self.assertEqual(self.annotate(cid).status_code, 409)
        saved = self.get(f'/annotations/{cid}').json
        self.assertEqual(saved['segments'][0]['start_s'], .1)
        self.assertEqual(saved['flag_ts'], .5)

    def test_database_enforces_append_only_even_without_api(self):
        cid = self.add()
        self.annotate(cid, segments=[{'start_s':0,'end_s':1,'label':'Safe'}])
        with closing(sqlite3.connect(self.app.config['DATABASE'])) as db, db:
            for command in ["UPDATE annotations SET label='Misleading'", 'DELETE FROM annotations', 'DELETE FROM segments', 'UPDATE segments SET start_s=.2']:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(command)

    def test_wait_and_every_pass_one_read_path_remain_sealed(self):
        one, two = self.add(1), self.add(2)
        self.assertEqual(self.post('/lock-pass1').status_code, 409)
        self.annotate(one)
        self.annotate(two)
        self.assertEqual(self.post('/lock-pass1').status_code, 200)
        self.assertEqual(self.post('/start-pass2').status_code, 423)
        self.assertEqual(self.annotate(one, 2).status_code, 423)
        for path in [f'/annotations/{one}?pass=1','/agreement','/revisions','/export','/export?format=json']:
            self.assertEqual(self.get(path).status_code, 423, path)
        clips = self.get('/clips').json
        self.assertFalse(any('rationale' in c or 'label' in c for c in clips))
        self.assertEqual(self.annotate(one).status_code, 423)
        self.unlock_wait()
        self.assertEqual(self.post('/start-pass2').status_code, 200)
        self.assertEqual(self.annotate(one, 2).status_code, 201)
        self.assertEqual(self.get('/export').status_code, 423)
        self.assertEqual(self.annotate(two, 2).status_code, 201)
        self.assertEqual(self.get('/state').json['phase'], 'complete')
        self.assertEqual(self.get('/agreement').status_code, 200)
        self.assertEqual(self.get(f'/annotations/{one}?pass=1').status_code, 200)

    def test_wait_duration_is_snapshotted_at_lock(self):
        cid = self.add()
        self.annotate(cid)
        self.post('/lock-pass1')
        self.app.config['PASS2_DELAY_MINUTES'] = 0
        self.assertEqual(self.post('/start-pass2').status_code, 423)
        self.assertEqual(self.get('/state').json['delay_minutes'], 60)

    def test_workspaces_are_isolated_and_practice_has_no_delay(self):
        cid = self.add()
        self.headers = {'X-Workspace': 'practice'}
        self.assertEqual(self.get('/clips').json, [])
        self.assertEqual(self.get(f'/captions/{cid}').status_code, 404)
        practice_id = self.add(2)
        self.annotate(practice_id)
        self.post('/lock-pass1')
        self.assertEqual(self.post('/start-pass2').status_code, 200)
        self.assertEqual(self.get('/state').json['delay_minutes'], 0)

    def test_caption_scoring_is_independent_and_immutable(self):
        cid = self.add()
        self.assertEqual(self.post(f'/judge/{cid}').status_code, 409)
        self.assertEqual(self.post(f'/caption/{cid}', {'mode':'gemini','consent':True}).status_code, 503)
        self.assertEqual(self.post(f'/caption/{cid}', {'mode':'manual','caption_text':'A quiet tone plays.','model':'manual test'}).status_code, 201)
        self.assertEqual(self.post(f'/caption/{cid}', {'mode':'manual','caption_text':'Changed','model':'manual'}).status_code, 409)
        base = {'accuracy':5,'omission':4,'hallucination':5,'rationale':'The tone is audible; the caption makes no unsupported claims.'}
        for bad in [0, 6, 2.5, '4', True]:
            self.assertEqual(self.post(f'/scores/{cid}', {**base,'accuracy':bad}).status_code, 400)
        self.assertEqual(self.post(f'/scores/{cid}', base).status_code, 201)
        self.assertEqual(self.post(f'/scores/{cid}', base).status_code, 409)
        received = {}
        def judge(path, mime, key, model, caption):
            received.update(caption=caption, mime=mime)
            return {'accuracy':4,'omission':2,'hallucination':5,'rationale':'Test provider response: one point accuracy gap and two point omission gap.'}
        fake = types.ModuleType('backend.ai')
        fake.evaluate_media = judge
        self.app.config['GEMINI_API_KEY'] = 'unit-test-placeholder'
        with patch.dict(sys.modules, {'backend.ai':fake}):
            self.assertEqual(self.post(f'/judge/{cid}', {'consent':False}).status_code, 400)
            self.assertEqual(self.post(f'/judge/{cid}', {'consent':True}).status_code, 201)
        self.assertEqual(received, {'caption':'A quiet tone plays.','mime':'audio/wav'})
        comparison = self.get('/comparison').json
        self.assertEqual(comparison['comparisons'], 3)
        self.assertEqual(comparison['within_one'], 2)
        self.assertEqual(comparison['within_one_pct'], 66.67)
        self.assertEqual(self.post(f'/judge/{cid}', {'consent':True}).status_code, 409)

    def test_exports_and_guideline_changes_are_evidence_linked(self):
        cid = self.finish(different=True)
        self.assertEqual(self.post('/revisions', {'rule_id':'R6','clip_ids':['imaginary'],'issue':'A vague interpretation.','rewrite':'A clearer definition.'}).status_code, 400)
        self.assertEqual(self.post('/revisions', {'rule_id':'R6','clip_ids':[cid],'issue':'The audio-only rule does not specify how to handle tones.','rewrite':'For non-speech tones, label only audible events and avoid inferred intent.'}).status_code, 201)
        export = self.get('/export')
        self.assertEqual(export.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(export.data)) as archive:
            self.assertTrue({'labels.csv','segments.csv','caption_scores.csv','clips.csv','study.json','guideline_v2.md','CHANGELOG.md','RESULTS.md'}.issubset(set(archive.namelist())))
            self.assertIn('non-speech tones', archive.read('guideline_v2.md').decode())
            data = json.loads(archive.read('study.json'))
            self.assertEqual(data['agreement']['agreement_pct'], 0)
            self.assertNotIn('media_path', data['clips'][0])

    def test_source_and_cross_site_guards(self):
        self.assertEqual(self.client.post('/api/lock-pass1', json={}, headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/state', base_url='http://evil.example').status_code,403)
        self.assertEqual(self.get('/state?workspace=unknown').status_code,200)  # explicit header wins
        self.assertEqual(self.client.get('/api/state?workspace=unknown').status_code,404)
        self.assertEqual(self.client.get('/data/annotateqa.sqlite3').status_code,404)

    def test_agreement_metrics_known_example_and_degenerate_cases(self):
        result = calculate_agreement(['Safe','Safe','Needs review','Needs review'], ['Safe','Needs review','Safe','Needs review'])
        self.assertEqual(result['agreement_pct'],50)
        self.assertEqual(result['kappa'],0)
        self.assertIsNone(calculate_agreement(['Safe'],['Safe'])['kappa'])
        self.assertIsNone(calculate_agreement([],[])['agreement_pct'])
        with self.assertRaises(ValueError):
            calculate_agreement(['Safe'],[])


if __name__ == '__main__':
    unittest.main()
