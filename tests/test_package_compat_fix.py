import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/fix-package-openwrt-25126.sh'
WORKER=ROOT/'package/xtlsprovpn/files/usr/bin/xray-lab-package'

@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class PackageCompatFix(unittest.TestCase):
    def test_exact_legacy_guard_is_corrected_unknown_code_is_preserved_and_repeat_is_noop(self):
        new='    case "${DISTRIB_RELEASE:-}" in 25.12.5|25.12.6) ;; *) exit 1 ;; esac\n    [ "$(uname -m)" = aarch64 ] || exit 1'
        old='    [ "${DISTRIB_RELEASE:-}" = 25.12.5 ] && [ "$(uname -m)" = aarch64 ] || exit 1'
        expected=WORKER.read_text()
        for case in ('legacy','current','unknown','non-root'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                r=Path(temp);(r/'usr/bin').mkdir(parents=True);(r/'root').mkdir();(r/'bin').mkdir()
                worker=r/'usr/bin/xray-lab-package'
                source=expected.replace(new,old).replace('OpenWrt 25.12.5/25.12.6 / aarch64.','OpenWrt 25.12.5 / aarch64.') if case=='legacy' else 'custom code' if case=='unknown' else expected
                worker.write_text(source);worker.chmod(0o755)
                (r/'bin/id').write_text('#!/bin/sh\necho '+('1000' if case=='non-root' else '0')+'\n');(r/'bin/id').chmod(0o755)
                env=dict(os.environ,FX_PACKAGE_COMPAT_ROOT=str(r),PATH=str(r/'bin')+':'+os.environ['PATH'])
                p=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(p.returncode==0,case in ('legacy','current'),p.stdout+p.stderr)
                self.assertEqual(worker.read_text(),expected if case in ('legacy','current') else source)
                backups=list((r/'root').glob('xray-package-before-*'))
                self.assertEqual(len(backups),1 if case=='legacy' else 0)
                if case=='legacy':
                    self.assertEqual(backups[0].read_text(),source)
                    p=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=5)
                    self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(len(list((r/'root').iterdir())),1)
                self.assertFalse(list(worker.parent.glob('*.compat.*')))
