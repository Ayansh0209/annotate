"""Build a real 20-video / 10-audio dataset from Wikimedia Commons.

Requires network access. Preserves reported licences, source links and authors;
never creates labels, scores, or claims that the study has been completed.
"""
import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.db import connect, initialize

API = 'https://commons.wikimedia.org/w/api.php'
USER_AGENT = 'AnnotateQA/1.0 (educational local annotation workbench; https://www.mediawiki.org/wiki/API:Etiquette)'
MAX_BYTES = 25 * 1024 * 1024

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def validate_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('commons.wikimedia.org', 'upload.wikimedia.org') or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Only HTTPS Wikimedia source and media hosts are accepted.')

def fetch(url, limit=MAX_BYTES):
    validate_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.build_opener(SafeRedirect()).open(request, timeout=30) as response:
        if int(response.headers.get('Content-Length','0')) > limit:
            raise ValueError('Media exceeds download size limit.')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Media exceeds download size limit.')
        return data

def plain(value):
    return html.unescape(re.sub('<[^>]+>', '', value or '')).strip()

def candidate_pages(kind, topic, offset=0):
    query = urllib.parse.urlencode({'action':'query','format':'json','generator':'search',
        'gsrsearch':f'filetype:{kind} {topic}', 'gsrnamespace':6,'gsrlimit':25,'gsroffset':offset,
        'prop':'videoinfo','viprop':'url|size|mime|mediatype|extmetadata|derivatives','vilimit':1})
    result = json.loads(fetch(API + '?' + query, 5 * 1024 * 1024))
    if 'error' in result:
        raise ValueError(result['error'].get('info','Wikimedia API error'))
    return result.get('query',{}).get('pages',{}).values()

def choose_source(info, kind):
    mime = info.get('mime','')
    url = info.get('url','')
    if kind == 'video':
        variants = [d for d in info.get('derivatives',[]) if 'webm' in d.get('type','') and 0 < d.get('width',0) <= 854]
        if variants:
            best = max(variants,key=lambda d:d.get('width',0))
            return best.get('src'), 'video/webm', '.webm'
        if mime in ('video/webm','video/ogg','video/mp4'):
            return url,mime,{'video/webm':'.webm','video/ogg':'.ogv','video/mp4':'.mp4'}[mime]
    elif mime in ('audio/ogg','application/ogg','audio/mpeg','audio/wav','audio/x-wav'):
        return url, 'audio/ogg' if 'ogg' in mime else mime, '.ogg' if 'ogg' in mime else '.mp3' if mime=='audio/mpeg' else '.wav'
    return None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--videos',type=int,default=20)
    parser.add_argument('--audio',type=int,default=10)
    args=parser.parse_args()
    if not 0 <= args.videos <= 100 or not 0 <= args.audio <= 100:
        parser.error('Each target must be between 0 and 100.')
    folder=ROOT/'data'/'media';folder.mkdir(parents=True,exist_ok=True)
    database=ROOT/'data'/'annotateqa.sqlite3';initialize(database)
    topics={'video':['nature','cooking','train','street','sport','craft','water','science'],
            'audio':['bird song','rain','piano','bell','train','English pronunciation','wind','water']}
    errors=[]
    with closing(connect(database)) as db, db:
        if db.execute("SELECT locked_at FROM studies WHERE id='study'").fetchone()[0]:
            raise SystemExit('The study is locked. Its dataset cannot be changed.')
        for kind,target in [('video',args.videos),('audio',args.audio)]:
            count=db.execute("SELECT count(*) FROM clips WHERE study_id='study' AND type=?",(kind,)).fetchone()[0]
            for topic in topics[kind]:
                if count >= target: break
                try: pages=candidate_pages(kind,topic)
                except (urllib.error.URLError,ValueError) as error:
                    raise SystemExit(f'Cannot reach Wikimedia: {error}. Existing data was preserved; try again when network access is available.')
                for page in pages:
                    if count>=target:break
                    info=(page.get('videoinfo') or [{}])[0];metadata=info.get('extmetadata',{})
                    licence=plain(metadata.get('LicenseShortName',{}).get('value',''))
                    licence_url=plain(metadata.get('LicenseUrl',{}).get('value',''))
                    if not (licence.startswith(('CC BY','CC0')) or licence in ('Public domain','PD')):continue
                    duration=float(info.get('duration',0) or 0)
                    if not 2 <= duration <= 60:continue
                    source=choose_source(info,kind)
                    if not source:continue
                    url,mime,suffix=source
                    cid='commons-'+str(page['pageid'])
                    if db.execute('SELECT 1 FROM clips WHERE id=?',(cid,)).fetchone():continue
                    try:
                        content=fetch(url)
                        digest=hashlib.sha256(content).hexdigest()
                        if db.execute("SELECT 1 FROM clips WHERE study_id='study' AND sha256=?",(digest,)).fetchone():continue
                        name=cid+suffix;path=folder/name
                        author=plain(metadata.get('Artist',{}).get('value',''))
                        if not author:continue
                        description_url=info.get('descriptionurl','')
                        validate_url(description_url)
                        db.execute('BEGIN IMMEDIATE')
                        if db.execute("SELECT locked_at FROM studies WHERE id='study'").fetchone()[0]:
                            raise SystemExit('Study locked during collection; stopped without changing the locked dataset.')
                        db.execute('INSERT INTO clips VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(cid,'study',page['title'].removeprefix('File:'),kind,description_url,licence,author,duration,name,mime,digest,datetime.now(timezone.utc).isoformat()))
                        path.write_bytes(content)
                        db.commit()
                        count+=1
                        print(f'{kind} {count}/{target}: {page["title"]} [{licence}]',flush=True)
                    except (urllib.error.URLError,ValueError,sqlite3.Error,OSError) as error:
                        db.rollback();errors.append(f'{cid}: {type(error).__name__}')
                    time.sleep(.3)
                time.sleep(.5)
            print(f'{kind}: {count}/{target} collected.',flush=True)
        manifest=[{k:v for k,v in dict(r).items() if k!='media_path'} for r in db.execute("SELECT * FROM clips WHERE study_id='study'")]
        (ROOT/'data'/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        actual={k:sum(r['type']==k for r in manifest) for k in ('video','audio')}
        print('Actual dataset:',actual)
        print('Review each source licence and play every clip before annotating. Natural sound/nature clips are not a balanced moderation benchmark.')
        if actual['video']<args.videos or actual['audio']<args.audio:
            print('The requested target was not reached. Add remaining licensed media through the app. No missing clips were fabricated.')
        if errors:print('Skipped downloads:',len(errors))

if __name__=='__main__':
    main()
