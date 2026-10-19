"""Temporary offline build helper; restores only public npm package bytes from local caches."""
import base64
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tarfile
from urllib.parse import unquote

ROOT=pathlib.Path(__file__).resolve().parent
CACHE=pathlib.Path(r'C:\Users\1atre\AppData\Local\npm-cache\_cacache')
CATALOG=ROOT/'npm-cache-catalog.json'
if CATALOG.exists():
    catalog=json.loads(CATALOG.read_text())
else:
    catalog={}
    for p in (CACHE/'index-v5').rglob('*'):
        if not p.is_file(): continue
        for line in p.read_text(errors='ignore').splitlines():
            try: entry=json.loads(line.split('\t',1)[1]); key=entry.get('key','')
            except (ValueError,IndexError): continue
            prefix='make-fetch-happen:request-cache:https://registry.npmjs.org/'
            if not key.startswith(prefix) or not key.endswith('.tgz') or '/-/' not in key: continue
            suffix=unquote(key[len(prefix):]); name=suffix.split('/-/')[0]
            match=re.search(r'-(\d+\.\d+\.\d+(?:-[\w.]+)?)\.tgz$',suffix)
            if match and entry.get('integrity'): catalog.setdefault(name,{})[match.group(1)]=entry['integrity']
    CATALOG.write_text(json.dumps(catalog))
print('Indexed public cached packages:',len(catalog),flush=True)
NODE=r'C:\Program Files\nodejs\node.exe'
SEMVER=r'C:\Program Files\nodejs\node_modules\npm\node_modules\semver'
resolver="const s=require(process.argv[1]); let b='';process.stdin.on('data',d=>b+=d);process.stdin.on('end',()=>{let a=JSON.parse(b);console.log(JSON.stringify(a.map(([v,r])=>s.maxSatisfying(v,r))))});"

def select(requests):
    data=[[list(catalog.get(n,{})),r] for n,r in requests]
    proc=subprocess.run([NODE,'-e',resolver,SEMVER],input=json.dumps(data),text=True,capture_output=True,check=True)
    return json.loads(proc.stdout)

project=ROOT/'annotateqa'
package=json.loads((project/'package.json').read_text())
pending=list({**package['dependencies'],**package['devDependencies']}.items())
installed={}; missing=[]
while pending:
    batch=pending;pending=[];choices=select(batch)
    for (name,requested),version in zip(batch,choices):
        if name in installed: continue
        if not version:
            missing.append((name,requested));continue
        integrity=catalog[name][version]
        algorithm,encoded=integrity.split('-',1)
        digest=base64.b64decode(encoded).hex()
        cached=CACHE/'content-v2'/algorithm/digest[:2]/digest[2:4]/digest[4:]
        if not cached.exists(): missing.append((name,version));continue
        raw=cached.read_bytes()
        if hashlib.new(algorithm,raw).hexdigest()!=digest: raise ValueError('Cached integrity mismatch: '+name)
        dest=project/'node_modules'/name;dest.mkdir(parents=True,exist_ok=True)
        with tarfile.open(cached,'r:gz') as tar:
            for member in tar.getmembers():
                parts=pathlib.PurePosixPath(member.name).parts
                if len(parts)<2 or '..' in parts or member.issym() or member.islnk():continue
                relative=pathlib.Path(*parts[1:]);out=dest/relative
                if member.isdir():out.mkdir(parents=True,exist_ok=True)
                elif member.isfile():
                    out.parent.mkdir(parents=True,exist_ok=True)
                    out.write_bytes(tar.extractfile(member).read())
        installed[name]=version
        meta=json.loads((dest/'package.json').read_text(encoding='utf-8'))
        for dependency,requirement in meta.get('dependencies',{}).items():
            if dependency not in installed: pending.append((dependency,requirement))
        for dependency,requirement in meta.get('optionalDependencies',{}).items():
            if ('win32' in dependency or not any(platform in dependency for platform in ['linux','darwin','freebsd','android','aix','sunos','openbsd','netbsd'])) and not any(arch in dependency for arch in ['arm64','ia32']):
                if dependency not in installed and dependency in catalog:pending.append((dependency,requirement))
        print('Restored',name,version,flush=True)
print('Unavailable:',missing,flush=True)
(ROOT/'restored-npm-versions.json').write_text(json.dumps(installed,indent=2))
bin_dir=project/'node_modules'/'.bin';bin_dir.mkdir(exist_ok=True)
for name in ['vite','typescript']:
    dest=project/'node_modules'/name
    if not (dest/'package.json').exists():continue
    meta=json.loads((dest/'package.json').read_text(encoding='utf-8'));bins=meta.get('bin',{})
    if isinstance(bins,str):bins={name:bins}
    for command,target in bins.items():
        (bin_dir/(command+'.cmd')).write_text('@echo off\r\nnode "%~dp0..\\'+name+'\\'+target.replace('/','\\')+'" %*\r\n')
