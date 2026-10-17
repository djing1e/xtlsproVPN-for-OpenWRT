import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SHA='49389264f520f1f33cd99038dfd5d450342c662d'
APK='xtlsprovpn-1.1.1-r2.apk'
MOCK=r'''#!/usr/bin/env python3
import json,os,shutil,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);mode=os.environ['TEST_MODE'];a=sys.argv[1:]
with (r/'calls').open('a') as f:f.write(json.dumps(a)+'\n')
if a[:2]==['run','watch']:sys.exit(1 if mode=='build-failed' else 0)
if a[0]=='api':
 if a[1].endswith('/39040590500'):print((r/'run.json').read_text())
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
 for name in a[-3:]:shutil.copy2(name,assets/Path(name).name)
 if mode=='bad-upload':(assets/'update.json').write_text('{}')
elif op=='download':
 d=Path(a[a.index('--dir')+1])
 for x in assets.iterdir():shutil.copy2(x,d/x.name)
elif op=='edit':
 assert '--draft=false' in a and '--latest' in a
 d=json.loads(state.read_text());d['isDraft']=False;state.write_text(json.dumps(d))
else:raise RuntimeError(a)
'''

class PublishUIRelease(unittest.TestCase):
    def test_promotes_complete_artifact_only_after_checks(self):
        for mode in ['ok','build-failed','wrong-commit','bad-zip','bad-manifest','bad-upload']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                r=Path(tmp);bin=r/'bin';bin.mkdir();gh=bin/'gh';gh.write_text(MOCK);gh.chmod(0o755)
                data=b'private isolated APK fixture';digest=hashlib.sha256(data).hexdigest()
                m={'schema':1,'version':'1.1.1-r2','tag':'v1.1.1','openwrt':['25.12.5'],
                   'architectures':['aarch64'],'apk':{'name':APK,'size':len(data),'sha256':digest}}
                if mode=='bad-manifest':m['apk']['sha256']='a'*64
                with zipfile.ZipFile(r/'artifact.zip','w') as z:
                    z.writestr(APK,data);z.writestr('SHA256SUMS',digest+'  ./'+APK+'\n')
                    z.writestr('update.json',json.dumps(m))
                archive=(r/'artifact.zip').read_bytes()
                (r/'artifacts.json').write_text(json.dumps({'artifacts':[{'id':123,'name':'xtlsprovpn-1.1.1-openwrt-25.12.5-arm64',
                    'expired':False,'size_in_bytes':len(archive),'digest':'sha256:'+hashlib.sha256(archive).hexdigest()}]}))
                if mode=='bad-zip':(r/'artifact.zip').write_bytes(b'tampered')
                (r/'run.json').write_text(json.dumps({'head_sha':'b'*40 if mode=='wrong-commit' else SHA,
                                                     'status':'completed','conclusion':'success'}))
                env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],TEST_ROOT=str(r),TEST_MODE=mode,
                         GITHUB_REPOSITORY='djing1e/xtlsproVPN-for-OpenWRT',RUNNER_TEMP=str(r))
                p=subprocess.run(['bash',str(ROOT/'scripts/publish-ui-r2.sh')],env=env,cwd=ROOT,
                                 capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode==0,mode=='ok',p.stdout+p.stderr)
                calls=[json.loads(x) for x in (r/'calls').read_text().splitlines()]
                edits=[x for x in calls if x[:2]==['release','edit']]
                self.assertEqual(bool(edits),mode=='ok')
                if mode=='ok':
                    self.assertLess(next(i for i,x in enumerate(calls) if x[:2]==['release','download']),
                                    next(i for i,x in enumerate(calls) if x[:2]==['release','edit']))
                    self.assertEqual(sorted(x.name for x in (r/'assets').iterdir()),sorted([APK,'SHA256SUMS','update.json']))
                    self.assertFalse(json.loads((r/'state.json').read_text())['isDraft'])
                if mode=='bad-upload':self.assertTrue(json.loads((r/'state.json').read_text())['isDraft'])
                self.assertFalse(list(r.glob('xtls-ui-release.*')))

if __name__=='__main__':unittest.main()
