"""Verify publication ordering and checksum failures without GitHub writes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
APK='xtlsprovpn-1.1.0-r5.apk'
MOCK=r'''#!/usr/bin/env python3
import json,os,shutil,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);a=sys.argv[1:];mode=os.environ['TEST_MODE']
with (r/'calls').open('a') as f:f.write(json.dumps([Path(sys.argv[0]).name]+a)+'\n')
if Path(sys.argv[0]).name=='git':sys.exit(1 if mode=='source-changed' else 0)
if a[0]=='api':sys.stdout.buffer.write((r/'artifact.zip').read_bytes());sys.exit(0)
assert a[0]=='release',a
op=a[1];state=r/'state.json';assets=r/'published';assets.mkdir(exist_ok=True)
if op=='view':
 if not state.exists():sys.exit(1)
 fields=a[a.index('--json')+1]
 d=json.loads(state.read_text())
 if fields=='isDraft,targetCommitish':print(json.dumps(d))
 else:print(json.dumps({'url':'https://github.com/djing1e/xtlsproVPN-for-OpenWRT/releases/tag/v1.1.0','isDraft':d['isDraft']}))
elif op=='create':
 assert '--draft' in a and a[a.index('--target')+1]==os.environ['GITHUB_SHA']
 state.write_text(json.dumps({'isDraft':True,'targetCommitish':os.environ['GITHUB_SHA']}))
elif op=='upload':
 assert json.loads(state.read_text())['isDraft']
 for source in a[-2:]:shutil.copy2(source,assets/Path(source).name)
 if mode=='bad-upload':(assets/'xtlsprovpn-1.1.0-r5.apk').write_bytes(b'corrupt upload')
elif op=='download':
 target=Path(a[a.index('--dir')+1])
 for source in assets.iterdir():shutil.copy2(source,target/source.name)
elif op=='edit':
 assert '--draft=false' in a and '--latest' in a
 d=json.loads(state.read_text());d['isDraft']=False;state.write_text(json.dumps(d))
else:raise RuntimeError(a)
'''

class ReleasePublish(unittest.TestCase):
    def test_promotes_only_verified_bytes(self):
        for mode in ('new','existing-draft','published','bad-archive-sha','bad-apk-sha','bad-upload','wrong-draft-target','source-changed'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                r=Path(temp);tools=r/'tools';tools.mkdir();(r/'calls').touch()
                apk=b'isolated APK fixture';apk_sha=hashlib.sha256(apk).hexdigest()
                manifest=apk_sha+'  ./'+APK+'\n'
                with zipfile.ZipFile(r/'artifact.zip','w') as z:
                    z.writestr(APK,apk if mode!='bad-apk-sha' else apk+b'tampered')
                    z.writestr('SHA256SUMS',manifest)
                archive_sha=hashlib.sha256((r/'artifact.zip').read_bytes()).hexdigest()
                if mode=='bad-archive-sha':(r/'artifact.zip').write_bytes(b'tampered archive')
                for name in ('git','gh'):
                    p=tools/name;p.write_text(MOCK);p.chmod(0o755)
                if mode in ('existing-draft','published','wrong-draft-target'):
                    (r/'state.json').write_text(json.dumps({'isDraft':mode!='published','targetCommitish':'b'*40 if mode=='wrong-draft-target' else 'a'*40}))
                if mode=='published':
                    (r/'published').mkdir();(r/'published'/APK).write_bytes(apk);(r/'published/SHA256SUMS').write_text(manifest)
                source=(ROOT/'scripts/publish-release-v1.1.sh').read_text()
                source=source.replace('archive_sha=c90d8deb50a25128ec6f9360a88aff0cedf9e954150d826b3471aa3594d34af3','archive_sha='+archive_sha)
                source=source.replace('apk_sha=eb9c3e45141409d1d2e5eaabfaff2012518c9a7f01a1c8daf89844dfc8bfd8d2','apk_sha='+apk_sha)
                command=r/'publish';command.write_text(source)
                env={**os.environ,'TEST_ROOT':str(r),'TEST_MODE':mode,'GITHUB_REPOSITORY':'djing1e/xtlsproVPN-for-OpenWRT','GITHUB_SHA':'a'*40,'RUNNER_TEMP':str(r),'PATH':str(tools)+':'+os.environ['PATH']}
                result=subprocess.run(['bash',str(command)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)
                passed=mode in ('new','existing-draft','published')
                self.assertEqual(result.returncode==0,passed,result.stdout+result.stderr)
                calls=[json.loads(line) for line in (r/'calls').read_text().splitlines()]
                edits=[c for c in calls if c[:3]==['gh','release','edit']]
                self.assertEqual(bool(edits),mode in ('new','existing-draft'))
                if edits:
                    download=next(i for i,c in enumerate(calls) if c[:3]==['gh','release','download'])
                    edit=next(i for i,c in enumerate(calls) if c[:3]==['gh','release','edit'])
                    self.assertLess(download,edit)
                if passed:
                    self.assertFalse(json.loads((r/'state.json').read_text())['isDraft'])
                    self.assertEqual((r/'published'/APK).read_bytes(),apk)
                elif mode=='bad-upload':self.assertTrue(json.loads((r/'state.json').read_text())['isDraft'])
                if mode=='source-changed':self.assertFalse(any(c[0]=='gh' for c in calls))
                self.assertFalse(list(r.glob('xtls-release.*')))

if __name__=='__main__':unittest.main()
