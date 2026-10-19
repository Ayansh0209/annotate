import sqlite3
from contextlib import closing

SCHEMA = '''
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS studies (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
 locked_at TEXT, pass2_available_at TEXT, pass2_started_at TEXT,
 completed_at TEXT, delay_minutes REAL, guideline_version TEXT NOT NULL DEFAULT 'v1'
);
CREATE TABLE IF NOT EXISTS clips (
 id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(id),
 title TEXT NOT NULL, type TEXT NOT NULL CHECK(type IN ('video','audio')),
 source_url TEXT NOT NULL, licence TEXT NOT NULL, attribution TEXT NOT NULL,
 duration_s REAL NOT NULL CHECK(duration_s>0), media_path TEXT NOT NULL,
 mime TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(study_id,sha256)
);
CREATE TABLE IF NOT EXISTS annotations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id TEXT NOT NULL REFERENCES clips(id),
 pass INTEGER NOT NULL CHECK(pass IN (1,2)), label TEXT NOT NULL,
 rule_id TEXT NOT NULL, rationale TEXT NOT NULL, flagged INTEGER NOT NULL,
 flag_ts REAL, guideline_version TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(clip_id,pass)
);
CREATE TABLE IF NOT EXISTS segments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, annotation_id INTEGER NOT NULL REFERENCES annotations(id),
 start_s REAL NOT NULL, end_s REAL NOT NULL, label TEXT NOT NULL,
 CHECK(start_s>=0 AND end_s>start_s)
);
CREATE TABLE IF NOT EXISTS captions (
 clip_id TEXT PRIMARY KEY REFERENCES clips(id), caption_text TEXT NOT NULL,
 model TEXT NOT NULL, provenance TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS caption_scores (
 id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id TEXT NOT NULL REFERENCES captions(clip_id),
 scorer TEXT NOT NULL CHECK(scorer IN ('human','judge')),
 accuracy INTEGER NOT NULL CHECK(accuracy BETWEEN 1 AND 5),
 omission INTEGER NOT NULL CHECK(omission BETWEEN 1 AND 5),
 hallucination INTEGER NOT NULL CHECK(hallucination BETWEEN 1 AND 5),
 rationale TEXT NOT NULL, corrected_caption TEXT NOT NULL DEFAULT '',
 model TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(clip_id,scorer)
);
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, study_id TEXT NOT NULL REFERENCES studies(id),
 rule_id TEXT NOT NULL, clip_ids TEXT NOT NULL, issue TEXT NOT NULL,
 rewrite TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(study_id,rule_id)
);
CREATE TRIGGER IF NOT EXISTS annotations_no_update BEFORE UPDATE ON annotations BEGIN SELECT RAISE(ABORT,'Annotations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS annotations_no_delete BEFORE DELETE ON annotations BEGIN SELECT RAISE(ABORT,'Annotations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS segments_no_update BEFORE UPDATE ON segments BEGIN SELECT RAISE(ABORT,'Segments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS segments_no_delete BEFORE DELETE ON segments BEGIN SELECT RAISE(ABORT,'Segments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS scores_no_update BEFORE UPDATE ON caption_scores BEGIN SELECT RAISE(ABORT,'Scores are append-only'); END;
CREATE TRIGGER IF NOT EXISTS scores_no_delete BEFORE DELETE ON caption_scores BEGIN SELECT RAISE(ABORT,'Scores are append-only'); END;
CREATE TRIGGER IF NOT EXISTS captions_no_update BEFORE UPDATE ON captions BEGIN SELECT RAISE(ABORT,'Captions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS captions_no_delete BEFORE DELETE ON captions BEGIN SELECT RAISE(ABORT,'Captions are immutable'); END;
'''

def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def initialize(path):
    with closing(connect(path)) as db, db:
        db.executescript(SCHEMA)
        db.executemany('INSERT OR IGNORE INTO studies(id,title,kind) VALUES(?,?,?)',
                       [('study','My annotation study','study'),('practice','Practice workspace','practice')])
