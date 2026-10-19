from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import secrets
import sqlite3
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from agreement import calculate_agreement
from backend.db import connect, initialize
from backend.domain import GUIDELINE_TEXT, LABELS, RUBRIC, RULES

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.mp4': ('video', 'video/mp4'), '.webm': ('video', 'video/webm'),
              '.ogv': ('video', 'video/ogg'), '.mp3': ('audio', 'audio/mpeg'),
              '.wav': ('audio', 'audio/wav'), '.ogg': ('audio', 'audio/ogg'), '.m4a': ('audio', 'audio/mp4')}


class ApiError(Exception):
    def __init__(self, message, status=400, **extra):
        self.message, self.status, self.extra = message, status, extra


def utcnow():
    return datetime.now(timezone.utc)


def timestamp():
    return utcnow().isoformat()


def text_field(data, key, minimum=1, maximum=4000):
    value = data.get(key)
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ApiError(f'{key.replace("_", " ").capitalize()} must contain {minimum}–{maximum} characters.')
    return value.strip()


def number(value, name, low=0, high=86400):
    if isinstance(value, bool):
        raise ApiError(f'{name} must be a number.')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ApiError(f'{name} must be a number.')
    if not math.isfinite(result) or not low <= result <= high:
        raise ApiError(f'{name} must be between {low} and {high}.')
    return result


def create_app(test_config=None):
    load_dotenv(ROOT / '.env')
    app = Flask(__name__, static_folder=None)
    app.config.update(DATA_DIR=str(ROOT / 'data'), MAX_CONTENT_LENGTH=50 * 1024 * 1024,
                      PASS2_DELAY_MINUTES=float(os.getenv('PASS2_DELAY_MINUTES', '60')),
                      GEMINI_API_KEY=os.getenv('GEMINI_API_KEY', ''), GEMINI_MODEL=os.getenv('GEMINI_MODEL', 'gemini-3.8-flash'))
    if test_config:
        app.config.update(test_config)
    data_dir = Path(app.config['DATA_DIR'])
    (data_dir / 'media').mkdir(parents=True, exist_ok=True)
    app.config['DATABASE'] = str(data_dir / 'annotateqa.sqlite3')
    initialize(app.config['DATABASE'])

    def db():
        if 'db' not in g:
            g.db = connect(app.config['DATABASE'])
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        if 'db' in g:
            g.db.close()

    def study_id():
        sid = request.headers.get('X-Workspace') or request.args.get('workspace', 'study')
        if sid not in ('study', 'practice'):
            raise ApiError('Unknown workspace.', 404)
        return sid

    def study():
        return dict(db().execute('SELECT * FROM studies WHERE id=?', (study_id(),)).fetchone())

    def counts():
        sid = study_id()
        total = db().execute('SELECT count(*) FROM clips WHERE study_id=?', (sid,)).fetchone()[0]
        done = {p: db().execute('SELECT count(*) FROM annotations a JOIN clips c ON c.id=a.clip_id WHERE c.study_id=? AND a.pass=?', (sid, p)).fetchone()[0] for p in (1, 2)}
        return total, done

    def complete():
        total, done = counts()
        return total > 0 and done[2] == total

    def hidden():
        return bool(study()['locked_at']) and not complete()

    def require_unblinded():
        if hidden():
            raise ApiError('First-pass information is sealed until every second-pass annotation is submitted.', 423)

    def require_complete():
        if not complete():
            raise ApiError('Complete both annotation passes before opening this report.', 423)

    def clip_row(clip_id):
        row = db().execute('SELECT * FROM clips WHERE id=? AND study_id=?', (clip_id, study_id())).fetchone()
        if not row:
            raise ApiError('Clip not found in this workspace.', 404)
        return dict(row)

    def public_clip(row):
        result = {k: v for k, v in dict(row).items() if k != 'media_path'}
        result['media_url'] = f'/media/{row["id"]}'
        return result

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ApiError('Send a JSON object.')
        return data

    @app.before_request
    def guard_origin():
        # This app is deliberately local-only. Reject DNS rebinding and cross-site writes.
        if request.host.split(':')[0] not in ('localhost', '127.0.0.1', '[::1]'):
            raise ApiError('Use localhost or 127.0.0.1 to access this local workspace.', 403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            permitted = {request.host_url.rstrip('/'), 'http://127.0.0.1:5173', 'http://localhost:5173'}
            if origin and origin not in permitted:
                raise ApiError('Cross-site writes are not allowed.', 403)

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.path.startswith('/api'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error=error.message, **error.extra), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(_):
        db().rollback()
        return jsonify(error='This record already exists or violates the study constraints. Refresh and try again.'), 409

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', service='AnnotateQA')

    @app.get('/api/state')
    def state():
        current = study()
        total, done = counts()
        available = datetime.fromisoformat(current['pass2_available_at']) if current['pass2_available_at'] else None
        remaining = max(0, math.ceil((available - utcnow()).total_seconds())) if available else 0
        phase = 'complete' if complete() else ('pass2' if current['pass2_started_at'] else ('waiting' if current['locked_at'] else 'pass1'))
        scores = db().execute('SELECT s.scorer,count(*) AS n FROM caption_scores s JOIN clips c ON c.id=s.clip_id WHERE c.study_id=? GROUP BY s.scorer', (study_id(),)).fetchall()
        return jsonify(**current, total=total, pass1_count=done[1], pass2_count=done[2], phase=phase,
                       remaining_seconds=remaining, blind=hidden(), ai_configured=bool(app.config['GEMINI_API_KEY']),
                       ai_model=app.config['GEMINI_MODEL'], score_counts={r['scorer']: r['n'] for r in scores},
                       configured_delay_minutes=0 if study_id() == 'practice' else app.config['PASS2_DELAY_MINUTES'])

    @app.get('/api/guidelines')
    def guidelines():
        return jsonify(version='v1', labels=LABELS, rules=RULES, rubric=RUBRIC)

    @app.get('/api/clips')
    def clips():
        rows = db().execute('SELECT * FROM clips WHERE study_id=? ORDER BY created_at,id', (study_id(),)).fetchall()
        pass_number = 2 if study()['locked_at'] else 1
        result = []
        for row in rows:
            item = public_clip(row)
            item['annotated'] = bool(db().execute('SELECT 1 FROM annotations WHERE clip_id=? AND pass=?', (row['id'], pass_number)).fetchone())
            item['has_caption'] = bool(db().execute('SELECT 1 FROM captions WHERE clip_id=?', (row['id'],)).fetchone())
            item['human_scored'] = bool(db().execute("SELECT 1 FROM caption_scores WHERE clip_id=? AND scorer='human'", (row['id'],)).fetchone())
            result.append(item)
        if study()['locked_at']:
            # Stable, shuffled order differs from pass 1 without exposing earlier labels.
            result.sort(key=lambda item: hashlib.sha256((study()['locked_at'] + item['id']).encode()).hexdigest())
        return jsonify(result)

    @app.post('/api/clips')
    def upload():
        if study()['locked_at']:
            raise ApiError('The dataset is frozen after locking pass 1.', 409)
        form = request.form.to_dict()
        title = text_field(form, 'title', maximum=150)
        licence = text_field(form, 'licence', maximum=150)
        attribution = text_field(form, 'attribution', maximum=500)
        source = text_field(form, 'source_url', maximum=2000)
        if not (source == 'Original work' or urlparse(source).scheme == 'https'):
            raise ApiError('Use an HTTPS source page or “Original work”.')
        duration = number(form.get('duration_s'), 'Duration', 0.01, 600)
        media = request.files.get('file')
        suffix = Path(media.filename or '').suffix.lower() if media else ''
        if not media or suffix not in EXTENSIONS:
            raise ApiError('Choose an MP4, WebM, OGV, MP3, WAV, OGG or M4A file.')
        content = media.read()
        if not content:
            raise ApiError('The media file is empty.')
        # Basic container validation prevents arbitrary documents masquerading as media.
        head = content[:64]
        valid = ((suffix in ('.mp4', '.m4a') and b'ftyp' in head) or
                 (suffix == '.webm' and head.startswith(b'\x1aE\xdf\xa3')) or
                 (suffix in ('.ogg', '.ogv') and head.startswith(b'OggS')) or
                 (suffix == '.wav' and head.startswith(b'RIFF') and b'WAVE' in head) or
                 (suffix == '.mp3' and (head.startswith(b'ID3') or (len(head) > 1 and head[0] == 255 and head[1] & 224 == 224))))
        if not valid:
            raise ApiError('File contents do not match the selected media format.')
        digest = hashlib.sha256(content).hexdigest()
        cid = uuid.uuid4().hex[:16]
        filename = f'{cid}{suffix}'
        path = data_dir / 'media' / filename
        try:
            db().execute('BEGIN IMMEDIATE')
            if study()['locked_at']:
                raise ApiError('The dataset was just locked. Refresh the page.', 409)
            db().execute('INSERT INTO clips VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                         (cid, study_id(), title, EXTENSIONS[suffix][0], source, licence, attribution, duration, filename, EXTENSIONS[suffix][1], digest, timestamp()))
            path.write_bytes(content)
            db().commit()
        except Exception:
            db().rollback()
            path.unlink(missing_ok=True)
            raise
        return jsonify(public_clip(clip_row(cid))), 201

    @app.get('/media/<clip_id>')
    def media(clip_id):
        # Media contains no labels. Range responses enable HTML5 scrubbing.
        row = db().execute('SELECT media_path,mime FROM clips WHERE id=?', (clip_id,)).fetchone()
        if not row:
            raise ApiError('Media not found.', 404)
        return send_from_directory(data_dir / 'media', row['media_path'], mimetype=row['mime'], conditional=True)

    @app.get('/api/annotations/<clip_id>')
    def annotation(clip_id):
        clip_row(clip_id)
        p = request.args.get('pass', '1')
        if p not in ('1', '2'):
            raise ApiError('Pass must be 1 or 2.')
        if p == '1':
            require_unblinded()
        row = db().execute('SELECT * FROM annotations WHERE clip_id=? AND pass=?', (clip_id, int(p))).fetchone()
        if not row:
            return jsonify(None)
        result = dict(row)
        result['segments'] = [dict(s) for s in db().execute('SELECT * FROM segments WHERE annotation_id=?', (row['id'],))]
        return jsonify(result)

    @app.post('/api/annotate')
    def annotate():
        body = payload()
        row = clip_row(text_field(body, 'clip_id'))
        p = body.get('pass')
        if type(p) is not int or p not in (1, 2):
            raise ApiError('Pass must be 1 or 2.')
        label = body.get('label')
        rule = body.get('rule_id')
        if label not in LABELS or rule not in {r['id'] for r in RULES}:
            raise ApiError('Choose a valid label and guideline rule.')
        rationale = text_field(body, 'rationale', minimum=10)
        flagged = body.get('flagged', False)
        if type(flagged) is not bool:
            raise ApiError('Flagged must be true or false.')
        if rule == 'R8' and label == 'Needs review' and not flagged:
            raise ApiError('R8 uncertain or unplayable clips require a review flag.')
        flag_ts = number(body.get('flag_ts'), 'Flag timestamp', 0, row['duration_s']) if flagged else None
        segments = body.get('segments', [])
        if not isinstance(segments, list) or len(segments) > 100:
            raise ApiError('Provide at most 100 timestamped segments.')
        checked = []
        for segment in segments:
            if not isinstance(segment, dict) or segment.get('label') not in LABELS:
                raise ApiError('Each segment needs a valid label.')
            start = number(segment.get('start_s'), 'Segment start', 0, row['duration_s'])
            end = number(segment.get('end_s'), 'Segment end', 0, row['duration_s'])
            if end <= start:
                raise ApiError('Segment end must be after its start.')
            checked.append((start, end, segment['label']))
        db().execute('BEGIN IMMEDIATE')
        current = study()
        if p == 1 and current['locked_at']:
            raise ApiError('Pass 1 is locked and cannot be changed.', 423)
        if p == 2 and (not current['pass2_started_at'] or utcnow() < datetime.fromisoformat(current['pass2_available_at'])):
            raise ApiError('Start the blind second pass after the waiting period.', 423)
        cursor = db().execute('INSERT INTO annotations(clip_id,pass,label,rule_id,rationale,flagged,flag_ts,guideline_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                             (row['id'], p, label, rule, rationale, int(flagged), flag_ts, 'v1', timestamp()))
        db().executemany('INSERT INTO segments(annotation_id,start_s,end_s,label) VALUES(?,?,?,?)', [(cursor.lastrowid, *s) for s in checked])
        if p == 2 and complete():
            db().execute('UPDATE studies SET completed_at=? WHERE id=?', (timestamp(), study_id()))
        db().commit()
        return jsonify(saved=True, annotation_id=cursor.lastrowid), 201

    @app.post('/api/lock-pass1')
    def lock():
        payload()
        db().execute('BEGIN IMMEDIATE')
        if study()['locked_at']:
            raise ApiError('Pass 1 is already locked.', 409)
        total, done = counts()
        if not total or total != done[1]:
            raise ApiError('Annotate every clip before locking pass 1.', 409)
        delay = 0 if study_id() == 'practice' else number(app.config['PASS2_DELAY_MINUTES'], 'Delay', 0, 10080)
        now = utcnow()
        db().execute('UPDATE studies SET locked_at=?,pass2_available_at=?,delay_minutes=? WHERE id=?',
                     (now.isoformat(), (now + timedelta(minutes=delay)).isoformat(), delay, study_id()))
        db().commit()
        return jsonify(locked=True)

    @app.post('/api/start-pass2')
    def start_second():
        payload()
        db().execute('BEGIN IMMEDIATE')
        current = study()
        if not current['locked_at']:
            raise ApiError('Lock pass 1 first.', 423)
        if current['pass2_started_at']:
            raise ApiError('Pass 2 has already started.', 409)
        if utcnow() < datetime.fromisoformat(current['pass2_available_at']):
            raise ApiError('The blind-pass waiting period has not elapsed.', 423, available_at=current['pass2_available_at'])
        db().execute('UPDATE studies SET pass2_started_at=? WHERE id=?', (timestamp(), study_id()))
        db().commit()
        return jsonify(started=True)

    def agreement_data():
        require_complete()
        rows = db().execute('''SELECT c.id,c.title,a.label AS label1,b.label AS label2,
            a.rule_id AS rule1,b.rule_id AS rule2,a.rationale AS rationale1,b.rationale AS rationale2,
            a.flagged AS flagged1,b.flagged AS flagged2 FROM clips c
            JOIN annotations a ON a.clip_id=c.id AND a.pass=1
            JOIN annotations b ON b.clip_id=c.id AND b.pass=2 WHERE c.study_id=? ORDER BY c.id''', (study_id(),)).fetchall()
        metrics = calculate_agreement([r['label1'] for r in rows], [r['label2'] for r in rows])
        metrics['disagreements'] = [dict(r) for r in rows if r['label1'] != r['label2']]
        metrics['flagged'] = [dict(r) for r in rows if r['flagged1'] or r['flagged2']]
        metrics['actual_delay_minutes'] = study()['delay_minutes']
        metrics['measure'] = 'Intra-rater agreement: the same annotator across two passes.'
        return metrics

    @app.get('/api/agreement')
    def agreement():
        return jsonify(agreement_data())

    @app.get('/api/captions/<clip_id>')
    def caption_detail(clip_id):
        clip_row(clip_id)
        caption = db().execute('SELECT * FROM captions WHERE clip_id=?', (clip_id,)).fetchone()
        scores = [dict(r) for r in db().execute('SELECT * FROM caption_scores WHERE clip_id=? ORDER BY scorer', (clip_id,))]
        return jsonify(caption=dict(caption) if caption else None, scores=scores)

    def run_ai(clip, caption=None):
        if not app.config['GEMINI_API_KEY']:
            raise ApiError('Add GEMINI_API_KEY to .env and restart the server to enable Gemini.', 503)
        if payload().get('consent') is not True:
            raise ApiError('Confirm that this media may be sent to Gemini.', 400)
        from backend.ai import evaluate_media
        try:
            return evaluate_media(data_dir / 'media' / clip['media_path'], clip['mime'],
                                  app.config['GEMINI_API_KEY'], app.config['GEMINI_MODEL'], caption)
        except (TimeoutError, ValueError) as error:
            raise ApiError(str(error)[:400], 502)
        except Exception:
            app.logger.warning('Gemini request failed. No media, captions or credentials logged.')
            raise ApiError('Gemini request failed. Check the key, model availability, quota and connection, then retry.', 502)

    @app.post('/api/caption/<clip_id>')
    def create_caption(clip_id):
        clip = clip_row(clip_id)
        if db().execute('SELECT 1 FROM captions WHERE clip_id=?', (clip_id,)).fetchone():
            raise ApiError('This clip already has a fixed caption for evaluation.', 409)
        body = payload()
        if body.get('mode') == 'manual':
            caption_text = text_field(body, 'caption_text', maximum=10000)
            model = text_field(body, 'model', maximum=150)
            provenance = 'manual import; model attribution supplied by user'
        elif body.get('mode') == 'gemini':
            caption_text = run_ai(clip)
            model = app.config['GEMINI_MODEL']
            provenance = 'Gemini API; generated from media'
        else:
            raise ApiError('Choose manual or gemini caption mode.')
        db().execute('INSERT INTO captions VALUES(?,?,?,?,?)', (clip_id, caption_text, model, provenance, timestamp()))
        db().commit()
        return jsonify(saved=True), 201

    def validate_scores(body):
        values = []
        for field in RUBRIC:
            value = body.get(field)
            if type(value) is not int or not 1 <= value <= 5:
                raise ApiError(f'{field.capitalize()} must be an integer from 1 to 5.')
            values.append(value)
        return values, text_field(body, 'rationale', minimum=10)

    @app.post('/api/scores/<clip_id>')
    def human_score(clip_id):
        clip_row(clip_id)
        if not db().execute('SELECT 1 FROM captions WHERE clip_id=?', (clip_id,)).fetchone():
            raise ApiError('Create or import a caption first.', 409)
        body = payload()
        values, rationale = validate_scores(body)
        corrected = body.get('corrected_caption', '')
        if not isinstance(corrected, str) or len(corrected) > 10000:
            raise ApiError('Corrected caption must be text under 10,000 characters.')
        db().execute('INSERT INTO caption_scores(clip_id,scorer,accuracy,omission,hallucination,rationale,corrected_caption,model,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                     (clip_id, 'human', *values, rationale, corrected.strip(), 'human', timestamp()))
        db().commit()
        return jsonify(saved=True), 201

    @app.post('/api/judge/<clip_id>')
    def judge(clip_id):
        clip = clip_row(clip_id)
        if not db().execute("SELECT 1 FROM caption_scores WHERE clip_id=? AND scorer='human'", (clip_id,)).fetchone():
            raise ApiError('Submit your own scores before running the independent judge.', 409)
        if db().execute("SELECT 1 FROM caption_scores WHERE clip_id=? AND scorer='judge'", (clip_id,)).fetchone():
            raise ApiError('Judge scores already exist for this fixed caption.', 409)
        caption = db().execute('SELECT caption_text FROM captions WHERE clip_id=?', (clip_id,)).fetchone()[0]
        result = run_ai(clip, caption)
        if not isinstance(result, dict):
            raise ApiError('Gemini returned an invalid scoring response.', 502)
        values, rationale = validate_scores(result)
        db().execute('INSERT INTO caption_scores(clip_id,scorer,accuracy,omission,hallucination,rationale,model,created_at) VALUES(?,?,?,?,?,?,?,?)',
                     (clip_id, 'judge', *values, rationale, app.config['GEMINI_MODEL'], timestamp()))
        db().commit()
        return jsonify(saved=True), 201

    def comparison_data():
        rows = db().execute('''SELECT c.id,c.title,h.accuracy AS human_accuracy,h.omission AS human_omission,
            h.hallucination AS human_hallucination,j.accuracy AS judge_accuracy,j.omission AS judge_omission,
            j.hallucination AS judge_hallucination,h.rationale AS human_rationale,j.rationale AS judge_rationale
            FROM clips c JOIN caption_scores h ON h.clip_id=c.id AND h.scorer='human'
            JOIN caption_scores j ON j.clip_id=c.id AND j.scorer='judge' WHERE c.study_id=?''', (study_id(),)).fetchall()
        dimensions = {}
        for field in RUBRIC:
            matches = sum(abs(r[f'human_{field}'] - r[f'judge_{field}']) <= 1 for r in rows)
            dimensions[field] = {'within_one': matches, 'n': len(rows), 'pct': round(matches / len(rows) * 100, 2) if rows else None}
        matches = sum(d['within_one'] for d in dimensions.values())
        return {'n': len(rows), 'comparisons': len(rows) * 3, 'within_one': matches,
                'within_one_pct': round(matches / (len(rows) * 3) * 100, 2) if rows else None,
                'dimensions': dimensions, 'rows': [dict(r) for r in rows]}

    @app.get('/api/comparison')
    def comparison():
        return jsonify(comparison_data())

    @app.get('/api/revisions')
    def revisions():
        report = agreement_data()
        saved = [dict(r) for r in db().execute('SELECT * FROM revisions WHERE study_id=?', (study_id(),))]
        return jsonify(disagreements=report['disagreements'], revisions=saved)

    @app.post('/api/revisions')
    def revise():
        report = agreement_data()
        body = payload()
        rule = body.get('rule_id')
        if rule not in {r['id'] for r in RULES}:
            raise ApiError('Choose a valid guideline rule.')
        ids = body.get('clip_ids', [])
        allowed = {r['id'] for r in report['disagreements']}
        if not isinstance(ids, list) or not ids or any(not isinstance(cid, str) or cid not in allowed for cid in ids):
            raise ApiError('Link at least one actual disagreeing clip.')
        issue = text_field(body, 'issue', minimum=10)
        rewrite = text_field(body, 'rewrite', minimum=10)
        db().execute('INSERT INTO revisions(study_id,rule_id,clip_ids,issue,rewrite,created_at) VALUES(?,?,?,?,?,?)',
                     (study_id(), rule, json.dumps(ids), issue, rewrite, timestamp()))
        db().commit()
        return jsonify(saved=True), 201

    def safe_csv(rows, fields):
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            # Avoid formula execution when opening untrusted free text in Excel.
            writer.writerow({k: ("'" + str(v) if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else v) for k, v in dict(row).items() if k in fields})
        return '\ufeff' + output.getvalue()

    @app.get('/api/export')
    def export():
        require_unblinded()
        sid = study_id()
        clip_rows = [dict(r) for r in db().execute('SELECT * FROM clips WHERE study_id=?', (sid,))]
        labels = [dict(r) for r in db().execute('SELECT a.*,c.title FROM annotations a JOIN clips c ON c.id=a.clip_id WHERE c.study_id=? ORDER BY a.clip_id,a.pass', (sid,))]
        segments = [dict(r) for r in db().execute('SELECT s.*,a.clip_id,a.pass FROM segments s JOIN annotations a ON a.id=s.annotation_id JOIN clips c ON c.id=a.clip_id WHERE c.study_id=?', (sid,))]
        scores = [dict(r) for r in db().execute('SELECT s.*,c.title FROM caption_scores s JOIN clips c ON c.id=s.clip_id WHERE c.study_id=?', (sid,))]
        captions = [dict(r) for r in db().execute('SELECT p.* FROM captions p JOIN clips c ON c.id=p.clip_id WHERE c.study_id=?', (sid,))]
        revision_rows = [dict(r) for r in db().execute('SELECT * FROM revisions WHERE study_id=?', (sid,))]
        report = agreement_data() if complete() else None
        comparison = comparison_data()
        state_data = study()
        data = {'study': state_data, 'clips': [{k:v for k,v in r.items() if k != 'media_path'} for r in clip_rows], 'annotations': labels,
                'segments': segments, 'captions': captions, 'caption_scores': scores, 'agreement': report, 'judge_comparison': comparison, 'revisions': revision_rows}
        if request.args.get('format') == 'json':
            return send_file(io.BytesIO(json.dumps(data, indent=2).encode()), mimetype='application/json', as_attachment=True, download_name=f'annotateqa-{sid}.json')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('labels.csv', safe_csv(labels, ['clip_id','title','pass','label','rule_id','rationale','flagged','flag_ts','guideline_version','created_at']))
            archive.writestr('segments.csv', safe_csv(segments, ['clip_id','pass','start_s','end_s','label']))
            archive.writestr('caption_scores.csv', safe_csv(scores, ['clip_id','title','scorer','accuracy','omission','hallucination','rationale','corrected_caption','model','created_at']))
            archive.writestr('clips.csv', safe_csv(clip_rows, ['id','title','type','source_url','licence','attribution','duration_s','sha256']))
            archive.writestr('captions.csv', safe_csv(captions, ['clip_id','caption_text','model','provenance','created_at']))
            archive.writestr('study.json', json.dumps(data, indent=2))
            archive.writestr('guideline_v1.md', '# Annotation guideline v1\n\n' + GUIDELINE_TEXT)
            rewrites = {r['rule_id']: r['rewrite'] for r in revision_rows}
            v2 = '# Annotation guideline v2\n\n' + ('Evidence-linked revisions. Original passes remain pinned to v1.\n\n' if rewrites else 'No evidence-linked rule revisions recorded yet. Rules remain unchanged.\n\n')
            v2 += '\n\n'.join(f"## {r['id']} — {r['title']}\n{rewrites.get(r['id'], r['text'])}" for r in RULES)
            archive.writestr('guideline_v2.md', v2)
            changes = '# Guideline changelog\n\n' + ('\n\n'.join(f"## {r['rule_id']}\nClips: {r['clip_ids']}\n\nAmbiguity: {r['issue']}\n\nRewrite: {r['rewrite']}" for r in revision_rows) or 'No guideline changes have been recorded. No disagreements or rewrites are invented.')
            archive.writestr('CHANGELOG.md', changes)
            result_text = (f"Paired clips: {report['n']}\nAgreement: {report['agreement_pct']}%\nCohen’s kappa: {report['kappa']}\nConfusion matrix (rows=pass 1, columns=pass 2): {report['matrix']}" if report else 'Both passes have not been completed. No agreement result is available.')
            hard = (report['disagreements'] + [r for r in report['flagged'] if r not in report['disagreements']])[:3] if report else []
            hard_text = '\n'.join(f"- {r['title']}: pass 1 — {r['rationale1']}; pass 2 — {r['rationale2']}" for r in hard) or 'No flagged or disagreeing clips recorded. Add your own reflection after completing the study.'
            archive.writestr('RESULTS.md', f"# AnnotateQA — {state_data['title']}\n\nWorkspace: {state_data['kind']}\n\n## Goal and method\nVideo/audio annotation and AI caption QA. Same annotator, two blind passes under guideline v1. Server-enforced delay: {state_data['delay_minutes']} minutes.\n\n## Results\n{result_text}\n\nJudge within one point: {comparison['within_one_pct']}% across {comparison['comparisons']} dimension comparisons; {comparison['n']} paired captions. Null means not measured.\n\n## Three reflection candidates\nThese are candidates selected from disagreements/flags, not a claim that they were the hardest.\n{hard_text}\n\n## Data handling\nMedia bytes and API keys are excluded. Source and licence metadata are in clips.csv. Do not identify faces. Treat rationales as potentially sensitive. Gemini is an independent model comparison, not ground truth.\n")
        buffer.seek(0)
        return send_file(buffer, mimetype='application/zip', as_attachment=True, download_name=f'annotateqa-{sid}-evidence.zip')

    @app.get('/')
    @app.get('/<path:path>')
    def frontend(path=''):
        if path.startswith(('api/', 'media/', 'data/', '.')):
            raise ApiError('Not found.', 404)
        dist = ROOT / 'dist'
        if not (dist / 'index.html').exists():
            return 'Frontend not built. Run npm install && npm run build in annotateqa.', 503
        if path and (dist / path).is_file():
            return send_from_directory(dist, path)
        return send_from_directory(dist, 'index.html')

    return app


if __name__ == '__main__':
    application = create_app()
    port = int(os.getenv('PORT', '5000'))
    print(f'AnnotateQA running at http://127.0.0.1:{port}', flush=True)
    try:
        from waitress import serve
    except ImportError:
        # Offline local development fallback; never bind this to a public interface.
        application.run(host='127.0.0.1', port=port, debug=False, threaded=True)
    else:
        serve(application, host='127.0.0.1', port=port, threads=8)
