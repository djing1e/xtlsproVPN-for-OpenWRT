import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]/'router'


@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class UpdateDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.dest=self.root/'deployed';self.dest.mkdir();self.src=self.root/'source';self.src.mkdir()
        self.native=self.root/'netbird.uc';self.native.write_text('function f(){\n    let c=package_catalog(true);\n}\n');self.native.chmod(0o640)
        self.original=self.native.read_bytes()
        (self.dest/'admin.uc').write_text('// existing admin')
        (self.dest/'ssh.uc').write_text('// old bridge')
        (self.dest/'admin-worker').write_text('# old worker\n')
        self.fail=self.root/'fail'
        entry=self.dest/'ssh-entry';entry.write_text('#!/bin/sh\n[ ! -f '+str(self.fail)+' ] || exit 1\necho \'{"schema":1,"ok":true,"data":{"plans":[]}}\'\n');entry.chmod(0o700)
        for name in ('updates.uc','update-worker','admin-worker'):
            shutil.copy(BASE/name,self.src/name)
        (self.src/'ssh.uc').write_text("print('{}');")
        bins=self.root/'bin';bins.mkdir()
        (bins/'id').write_text('#!/bin/sh\necho 0\n');(bins/'id').chmod(0o700)
        self.env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'])
        text=(BASE/'upgrade-updates.sh').read_text().replace('/etc/xtlspro-bot',str(self.dest)).replace('/usr/share/xray/lab/netbird.uc',str(self.native)).replace('/var/run',str(self.root/'run')).replace('/root/xtls-before-bot-updates.',str(self.root/'backup.'))
        self.script=self.src/'upgrade-updates.sh';self.script.write_text(text)

    def call(self):
        return subprocess.run(['sh',str(self.script)],env=self.env,capture_output=True,text=True,timeout=15)

    def test_deploy_preserves_native_mode_and_adds_pin_without_restart(self):
        result=self.call()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('FX_NETBIRD_EXPECTED_VERSION',self.native.read_text())
        self.assertEqual(self.native.stat().st_mode&0o777,0o640)
        self.assertEqual((self.dest/'update-worker').stat().st_mode&0o777,0o700)
        self.assertEqual((self.dest/'updates.uc').stat().st_mode&0o777,0o600)
        self.assertEqual(self.call().returncode,0)
        self.assertEqual(self.native.read_text().count("getenv('FX_NETBIRD_EXPECTED_VERSION')"),1)

    def test_failed_probe_restores_old_native_and_helpers(self):
        self.fail.touch()
        result=self.call()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.native.read_bytes(),self.original)
        self.assertEqual((self.dest/'ssh.uc').read_text(),'// old bridge')
        self.assertEqual((self.dest/'admin-worker').read_text(),'# old worker\n')
        self.assertFalse((self.dest/'update-worker').exists())
        self.assertFalse((self.dest/'updates.uc').exists())

    def test_unknown_native_layout_refused_before_changes(self):
        self.native.write_text('// unknown helper layout')
        result=self.call()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.dest/'ssh.uc').read_text(),'// old bridge')
        self.assertFalse(list(self.root.glob('backup.*')))
