import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
# The v1.4.1 hotfix intentionally downloads immutable historical bytes.
LIB = Path(__file__).resolve().parent/'fixtures/card-version-141'
SCRIPT = ROOT/'integrations/router-bot/router/fix-card-version.sh'

@unittest.skipUnless(shutil.which('ucode'), 'ucode runtime required')
class CardVersionFix(unittest.TestCase):
    def run_fixture(self, mode):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp)
            for name in ('lib','bin','tmp','root','run','mods'):
                (r/name).mkdir()
            for name in ('state.mjs', 'package_release.mjs', 'operation_error.mjs'):
                (r/'lib'/name).write_text((LIB/name).read_text())
            if mode == 'unknown':
                (r/'lib/state.mjs').write_text('custom router state')
            before = (r/'lib/state.mjs').read_bytes()
            (r/'mods/uci.uc').write_text('export function cursor() { return {}; };')
            mock = '''#!/usr/bin/env python3
import os,shutil,sys
from pathlib import Path
args=sys.argv[1:]; cmd=Path(sys.argv[0]).name
if cmd=='id': print('0')
elif cmd=='apk': print('xtlsprovpn-1.4.1-r1')
elif cmd=='curl':
 dst=Path(args[args.index('-o')+1]);src=Path(os.environ['FIX_LIB'])/dst.name
 dst.write_bytes(b'corrupt' if os.environ['FIX_MODE']=='corrupt' else src.read_bytes())
'''
            for name in ('id','apk','curl'):
                (r/'bin'/name).write_text(mock);(r/'bin'/name).chmod(0o755)
            (r/'bin/ucode').write_text('#!/bin/sh\nexec '+shutil.which('ucode')+' -L '+str(r/'mods')+' "$@"\n')
            (r/'bin/ucode').chmod(0o755)
            source=SCRIPT.read_text().replace('/usr/share/xray/lab',str(r/'lib')).replace('/var/run/xray-lab-control',str(r/'run')).replace('/root/xtls-before-card-version.',str(r/'root/backup.')).replace('/tmp/xtls-card-version.',str(r/'tmp/work.'))
            (r/'script.sh').write_text(source)
            env=dict(os.environ, PATH=str(r/'bin')+':'+os.environ['PATH'], FIX_LIB=str(LIB), FIX_MODE=mode)
            p=subprocess.run(['sh',str(r/'script.sh')],env=env,capture_output=True,text=True)
            if mode=='ok':
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                self.assertIn('Исправление установлено',p.stdout)
                self.assertEqual((r/'lib/state.mjs').read_bytes(),(LIB/'state.mjs').read_bytes())
            else:
                self.assertNotEqual(p.returncode,0)
                self.assertEqual((r/'lib/state.mjs').read_bytes(),before)

    def test_install_is_idempotent(self): self.run_fixture('ok')
    def test_unknown_state_is_preserved(self): self.run_fixture('unknown')
    def test_corrupted_download_is_rejected(self): self.run_fixture('corrupt')
