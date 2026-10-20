import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE='f4e7b0e67ae17549a6f42232b73295e52a68dd03'
APK='xtlsprovpn-1.4.1-r1.apk'; SERVER='xtls-router-bot-1.4.1.tar.gz'
MOCK=r'''#!/usr/bin/env python3
import json,os,shutil,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);mode=os.environ['TEST_MODE'];a=sys.argv[1:]
with (r/'calls').open('a') as f:f.write(json.dumps(a)+'\n')
if a[:2]==['run','watch']:sys.exit(1 if mode=='build-failed' else 0)
if a[0]=='api':
 if a[1].endswith('/39462485426'):print((r/'run.json').read_text())
 elif a[1].endswith('/artifacts'):print((r/'artifacts.json').read_text())
 else:sys.stdout.buffer.write((r/'artifact.zip').read_bytes())
 sys.exit(0)
assert a[0]=='release'
state=r/'state.json';assets=r/'assets';assets.mkdir(exist_ok=True);op=a[1]
if op=='view':
 if not state.exists():sys.exit(1)
 print(state.read_text())
elif op=='create':
 assert '--draft' in a
 state.write_text(json.dumps({'isDraft':True,'targetCommitish':a[a.index('--target')+1]}))
elif op=='upload':
 assert json.loads(state.read_text())['isDraft']
 for name in a[-4:]:shutil.copy2(name,assets/Path(name).name)
 if mode=='bad-upload':(assets/'update.json').write_text('{}')
elif op=='download':
 d=Path(a[a.index('--dir')+1])
 for x in assets.iterdir():shutil.copy2(x,d/x.name)
elif op=='edit':
 assert '--draft=false' in a and '--latest' in a
 d=json.loads(state.read_text());d['isDraft']=False;state.write_text(json.dumps(d))
else:raise RuntimeError(a)
'''

class Publish141(unittest.TestCase):
    def test_publish_only_source_bound_complete_verified_assets(self):
        spec=importlib.util.spec_from_file_location('pack_release_test',ROOT/'scripts/package-router-bot.py')
        pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)
        for mode in ('ok','verify-only','build-failed','wrong-commit','bad-zip','bad-manifest','bad-upload','source-changed'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                r=Path(tmp);bins=r/'bin';bins.mkdir()
                gh=bins/'gh';gh.write_text(MOCK);gh.chmod(0o755)
                git=bins/'git';git.write_text('#!/bin/sh\nif [ "$1" = rev-parse ]; then echo '+SOURCE+'; exit 0; fi\n[ "$TEST_MODE" != source-changed ]\n');git.chmod(0o755)
                pack.package(r/SERVER);server=(r/SERVER).read_bytes()
                apk=b'isolated release APK fixture';digest=hashlib.sha256(apk).hexdigest()
                manifest={'schema':1,'tag':'v1.4.1','version':'1.4.1-r1','openwrt':['25.12.5'],'architectures':['aarch64'],
                          'apk':{'name':APK,'size':len(apk),'sha256':digest}}
                if mode=='bad-manifest':manifest['apk']['sha256']='a'*64
                sums=digest+'  ./'+APK+'\n'+hashlib.sha256(server).hexdigest()+'  ./'+SERVER+'\n'
                with zipfile.ZipFile(r/'artifact.zip','w') as archive:
                    for name,data in [(APK,apk),(SERVER,server),('SHA256SUMS',sums),('update.json',json.dumps(manifest))]:archive.writestr(name,data)
                data=(r/'artifact.zip').read_bytes()
                (r/'artifacts.json').write_text(json.dumps({'artifacts':[{'id':123,'name':'xtlsprovpn-1.4.1-openwrt-25.12.5-arm64','expired':False,'size_in_bytes':len(data),'digest':'sha256:'+hashlib.sha256(data).hexdigest()}]}))
                if mode=='bad-zip':(r/'artifact.zip').write_bytes(b'corrupt')
                (r/'run.json').write_text(json.dumps({'head_sha':'b'*40 if mode=='wrong-commit' else SOURCE,'conclusion':'success','status':'completed'}))
                env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'],TEST_ROOT=str(r),TEST_MODE=mode,
                         RUNNER_TEMP=str(r),GITHUB_REPOSITORY='djing1e/xtlsproVPN-for-OpenWRT',PUBLISH_RELEASE='false' if mode=='verify-only' else 'true')
                result=subprocess.run(['bash',str(ROOT/'scripts/publish-v141.sh')],cwd=ROOT,env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode==0,mode in ('ok','verify-only'),result.stdout+result.stderr)
                calls=[json.loads(v) for v in (r/'calls').read_text().splitlines()] if (r/'calls').exists() else []
                edits=[v for v in calls if v[:2]==['release','edit']]
                self.assertEqual(bool(edits),mode=='ok')
                if mode=='ok':
                    self.assertLess(next(i for i,v in enumerate(calls) if v[:2]==['release','download']),next(i for i,v in enumerate(calls) if v[:2]==['release','edit']))
                    self.assertEqual({p.name for p in (r/'assets').iterdir()},{APK,SERVER,'SHA256SUMS','update.json'})
                if mode=='verify-only':self.assertFalse(any(v[0]=='release' for v in calls))
                if mode=='bad-upload':self.assertTrue(json.loads((r/'state.json').read_text())['isDraft'])
                self.assertFalse(list(r.glob('xtls-release-141.*')))

if __name__=='__main__':unittest.main()
