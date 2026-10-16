"""Check the physical-test checkpoint against the real journal, without a router."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'

class PowercutHarness(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.r=Path(self.temp.name);self.state=self.r/'state';self.state.mkdir()
        self.core=self.r/'core';self.core.write_text('original-core')
        self.work=self.r/'work';(self.work/'previous').mkdir(parents=True)
        (self.work/'previous-core').write_text('original-core')
        (self.work/'previous/subscription.json').write_text('original-catalogue')
        (self.state/'subscription.json').write_text('original-catalogue')
        self.tools=self.r/'tools';self.tools.mkdir()
        for name in ('sleep','sync','logger'):
            p=self.tools/name;p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o755)
        self.env={**os.environ,'PATH':str(self.tools)+':'+os.environ['PATH'],'FX_TEST_ROOT':str(self.r),'FX_SYNC_OWNER':'past-boot:123:1'}
        source=(FILES/'usr/bin/xray-lab-subscription-journal').read_text().replace('STATE=/etc/forkop-xray','STATE='+str(self.state)).replace('CORE=/etc/config/xray_core','CORE='+str(self.core)).replace('RUN=/var/run/xray-lab-control','RUN='+str(self.r/'run'))
        self.helper=self.r/'journal-helper';self.helper.write_text(source)
        result=subprocess.run(['sh',str(self.helper),'prepare',str(self.work)],env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.journal=self.state/'.subscription-transaction'
        script=(ROOT/'scripts/test-subscription-powercut-lab.sh').read_text()
        wrapper=script.split('cat > "$WORK/bin/mv" <<\'WRAP\'\n',1)[1].split('\nWRAP',1)[0]
        wrapper=wrapper.replace('/etc/config/xray_core',str(self.core)).replace('/etc/forkop-xray/.subscription-transaction',str(self.journal))
        self.wrapper=self.r/'mv';self.wrapper.write_text(wrapper)

    def call(self, source=None, target=None):
        return subprocess.run(['sh',str(self.wrapper),str(source or self.r/'core.sync-new'),str(target or self.core)],env=self.env,capture_output=True,text=True,timeout=5)

    def test_timeout_signals_failure_and_journal_restores_previous_files(self):
        (self.r/'core.sync-new').write_text('XTLS_POWERCUT_TEST_20261016')
        result=self.call()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('READY FOR POWER CUT:',result.stdout)
        self.assertTrue((self.r/'ready').exists());self.assertFalse((self.journal/'committed').exists())
        self.assertIn('XTLS_POWERCUT',self.core.read_text())
        # A new boot runs the real recovery helper, with no RAM staging or EXIT handler.
        result=subprocess.run(['sh',str(self.helper),'recover'],env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.core.read_text(),'original-core')
        self.assertEqual((self.state/'subscription.json').read_text(),'original-catalogue')
        self.assertFalse(self.journal.exists())

    def test_committed_transaction_never_advertises_cut_checkpoint(self):
        (self.journal/'committed').touch()
        (self.r/'core.sync-new').write_text('XTLS_POWERCUT_TEST_20261016')
        result=self.call();self.assertNotEqual(result.returncode,0)
        self.assertNotIn('READY FOR POWER CUT:',result.stdout);self.assertFalse((self.r/'ready').exists())

    def test_unrelated_rename_never_arms_checkpoint(self):
        source=self.r/'unrelated.new';target=self.r/'unrelated';source.write_text('data')
        result=self.call(source,target);self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.r/'ready').exists());self.assertEqual(self.core.read_text(),'original-core')

if __name__=='__main__':unittest.main()
