import base64,hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
FP='esLC1GpVsAr8dflLXB+KOlwEzPeccZp30F+F/7FMsD8'

class JoinTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bins=self.root/'bin';self.bins.mkdir();self.passport=self.root/'passport.json'
        self.calls=self.root/'calls'
        controller=self.bins/'xray-lab-bot'
        controller.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=json.loads(Path(sys.argv[2]).read_text())
if p.get('schema')!=1:sys.exit(1)
Path(os.environ['JOIN_CALLS']).write_text('prepare')
Path(os.environ['JOIN_PASSPORT']).write_text(json.dumps({'host':'100.124.249.61','port':22}))
print('xtls-enroll-v1:LONG-LEGACY-PASSPORT')
''');controller.chmod(0o700)
        for name,body in [('id','echo 0'),('ucode',':'),('dropbearkey',"echo 'Fingerprint: SHA256:"+FP+"'"),('jsonfilter', '''exec python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2][2:]])' "$2" "$4"''')]:
            path=self.bins/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o700)
        payload=self.root/'upgrade-hwid.sh';payload.write_text('#!/bin/sh\nprintf hwid >> "$JOIN_CALLS"\n')
        curl=self.bins/'curl';curl.write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then shift; cp "$JOIN_UPGRADE" "$1"; exit 0; fi; shift; done; exit 1\n');curl.chmod(0o700)
        self.payload=payload
        self.script=self.root/'join.sh' 
        self.script.write_text((BASE/'router/join.sh').read_text().replace('/usr/bin/xray-lab-bot',str(controller)).replace('/root/xtls-router-passport.json',str(self.passport)).replace('049cb558368566d9782ebd4aad9d3f280d32d456a6aac780a4736eacb45661e7',hashlib.sha256(payload.read_bytes()).hexdigest()))
        self.env=dict(os.environ,PATH=str(self.bins)+':'+os.environ['PATH'],JOIN_CALLS=str(self.calls),JOIN_PASSPORT=str(self.passport),JOIN_UPGRADE=str(payload))
    def call(self,code):return subprocess.run(['sh',str(self.script),code],env=self.env,capture_output=True,text=True,timeout=15)
    def test_one_command_prepares_profile_and_prints_only_compact_pair_code(self):
        code='xtls-profile-v1:'+base64.b64encode(json.dumps({'schema':1}).encode()).decode()
        r=self.call(code);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('xtls-pair-v1:100.124.249.61:22:'+FP,r.stdout)
        self.assertNotIn('LONG-LEGACY-PASSPORT',r.stdout)
        self.assertEqual(self.calls.read_text(),'preparehwid')
    def test_bad_hwid_upgrade_checksum_never_reports_pairing_success(self):
        self.payload.write_text('corrupt')
        code='xtls-profile-v1:'+base64.b64encode(json.dumps({'schema':1}).encode()).decode()
        result=self.call(code);self.assertNotEqual(result.returncode,0)
        self.assertNotIn('xtls-pair-v1:',result.stdout)
    def test_bad_or_oversized_profile_never_prepares(self):
        for code in ['bad','xtls-profile-v1:!','xtls-profile-v1:'+'A'*4097]:
            r=self.call(code);self.assertNotEqual(r.returncode,0)
            self.assertFalse(self.calls.exists())
    def test_missing_application_is_reported_before_preparation(self):
        (self.bins/'xray-lab-bot').unlink()
        self.assertNotEqual(self.call('xtls-profile-v1:e30=').returncode,0)
        self.assertFalse(self.calls.exists())
    def test_native_profile_rejection_is_not_reported_as_success(self):
        r=self.call('xtls-profile-v1:'+base64.b64encode(b'{}').decode())
        self.assertNotEqual(r.returncode,0);self.assertNotIn('xtls-pair-v1:',r.stdout)
