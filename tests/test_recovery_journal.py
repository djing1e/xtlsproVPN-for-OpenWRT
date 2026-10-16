"""Simulate process/boot boundaries using real helper and isolated persistent storage."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'package/xtlsprovpn/files'
FILES = 'subscription.json previous.json last-success-update device-hwid device-hwid-short'.split()

class Journal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.state = self.root/'state'; self.state.mkdir()
        self.run = self.root/'run'; self.core = self.root/'core'; self.core.write_text('old-core')
        self.work = self.root/'work'; (self.work/'previous').mkdir(parents=True)
        (self.work/'previous-core').write_text('old-core')
        for name in FILES[:3]:
            (self.state/name).write_text('old-'+name)
            (self.work/'previous'/name).write_text('old-'+name)
        source = (ROOT/'usr/bin/xray-lab-subscription-journal').read_text()
        source = source.replace('STATE=/etc/forkop-xray', 'STATE='+str(self.state)).replace('RUN=/var/run/xray-lab-control', 'RUN='+str(self.run)).replace('CORE=/etc/config/xray_core', 'CORE='+str(self.core))
        self.helper = self.root/'journal'; self.helper.write_text(source)
        tools=self.root/'tools';tools.mkdir()
        # Sync's ordering remains real code; disk persistence itself needs physical testing.
        for name in ('sync','logger'):
            p=tools/name;p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o755)
        self.env={**os.environ,'PATH':str(tools)+':'+os.environ['PATH'],'FX_SYNC_OWNER':'previous-boot:123:1'}
        self.journal=self.state/'.subscription-transaction'

    def command(self, action, expected=0, env=None):
        p=subprocess.run(['sh',str(self.helper),action,str(self.work)],env=env or self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,expected,p.stdout+p.stderr)
        return p

    def mutate(self):
        self.core.write_text('new-core')
        for name in FILES: (self.state/name).write_text('new-'+name)

    def assert_old(self):
        self.assertEqual(self.core.read_text(),'old-core')
        for name in FILES[:3]: self.assertEqual((self.state/name).read_text(),'old-'+name)
        for name in FILES[3:]: self.assertFalse((self.state/name).exists())

    def test_interrupt_before_apply_or_during_catalogue_publish(self):
        for stage in ('prepared','core-only','partial-catalogue','full-catalogue'):
            with self.subTest(stage=stage):
                self.command('prepare')
                if stage!='prepared':self.core.write_text('new-core')
                if stage=='partial-catalogue':(self.state/FILES[0]).write_text('partial')
                if stage=='full-catalogue':self.mutate()
                self.command('recover');self.assert_old()
                self.command('recover') # repeat boot is idempotent

    def test_committed_decision_survives_without_cleanup(self):
        self.command('prepare');self.mutate();self.command('commit')
        self.assertTrue((self.journal/'committed').exists())
        self.command('recover')
        self.assertEqual(self.core.read_text(),'new-core')
        self.assertFalse(self.journal.exists())

    def test_bad_backup_blocks_before_modifying_any_live_file(self):
        self.command('prepare');self.mutate()
        (self.journal/'previous-core').write_text('corrupt')
        self.command('recover',1)
        self.assertEqual(self.core.read_text(),'new-core');self.assertTrue(self.journal.exists())
        self.command('check',1)

    def test_incomplete_preparation_does_not_block_old_start(self):
        (self.state/'.subscription-transaction.new').mkdir()
        self.command('recover');self.assert_old()
        self.command('prepare');self.command('recover');self.assert_old()

    def test_active_owner_can_restart_candidate_but_other_process_cannot(self):
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        stat=Path('/proc/self/stat').read_text().split();started=stat[21]
        env={**self.env,'FX_SYNC_OWNER':f'{boot}:{stat[0]}:{started}'}
        self.command('prepare',env=env);self.mutate()
        self.command('recover',env=env)
        self.assertEqual(self.core.read_text(),'new-core');self.assertTrue(self.journal.exists())
        self.command('recover',1) # unrelated startup cannot roll back a live update
        (self.journal/'owner').write_text('previous-boot:123:1')
        self.command('recover');self.assert_old()

    def test_interrupted_restore_is_repeatable(self):
        self.command('prepare');self.mutate()
        # Files already restored before a second power cut are safe to restore again.
        (self.state/FILES[0]).write_text('old-'+FILES[0])
        self.command('recover');self.assert_old()

    def crash_wrapper(self, target):
        tools=self.root/'tools'
        wrapper=tools/'mv'
        wrapper.write_text("""#!/usr/bin/env python3
import os,sys,subprocess,signal
subprocess.run(['/bin/mv']+sys.argv[1:],check=True)
if sys.argv[-1]==os.environ.get('CRASH_AT'):
    os.killpg(os.getpgrp(),signal.SIGKILL)
""")
        wrapper.chmod(0o755)
        return {**self.env,'CRASH_AT':str(target)}

    def test_sigkill_at_publish_and_commit_boundaries(self):
        for boundary in ('prepared','core','catalogue','committed'):
            with self.subTest(boundary=boundary):
                target={'prepared':self.journal,'core':self.core,'catalogue':self.state/FILES[0],
                        'committed':self.journal/'committed'}[boundary]
                env=self.crash_wrapper(target)
                # Kill the entire update process group, including children, bypassing EXIT traps.
                script='"$1" prepare "$2"; printf new-core > "$3.new"; mv "$3.new" "$3"; printf new-catalogue > "$4.new"; mv "$4.new" "$4"; "$1" commit'
                self.helper.chmod(0o755)
                result=subprocess.run(['sh','-ec',script,'_',str(self.helper),str(self.work),str(self.core),str(self.state/FILES[0])],
                                      env=env,start_new_session=True,capture_output=True,timeout=5)
                self.assertNotEqual(result.returncode,0)
                # A fresh boot has no live owner token or RAM work directories.
                import shutil
                shutil.rmtree(self.run,ignore_errors=True)
                self.command('recover')
                if boundary=='committed':
                    self.assertEqual(self.core.read_text(),'new-core')
                    self.assertEqual((self.state/FILES[0]).read_text(),'new-catalogue')
                    self.core.write_text('old-core');(self.state/FILES[0]).write_text('old-'+FILES[0])
                else:self.assert_old()

    def test_sigkill_during_restore_then_retry(self):
        self.command('prepare');self.mutate()
        env=self.crash_wrapper(self.state/FILES[0])
        result=subprocess.run(['sh',str(self.helper),'recover'],env=env,start_new_session=True,capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0);self.assertTrue(self.journal.exists())
        self.command('recover');self.assert_old()

    def test_boot_restores_before_generating_config_and_blocks_damaged_backup(self):
        for damaged in (False, True):
            with self.subTest(damaged=damaged):
                self.command('prepare');self.mutate()
                if damaged:(self.journal/'previous-core').write_text('bad')
                source=(ROOT/'etc/init.d/xray_core').read_text()
                source=source.replace('/usr/bin/xray-lab-subscription-journal',str(self.helper))
                source=source.replace('/etc/forkop-xray/subscription.json',str(self.state/FILES[0]))
                source=source.replace('    mkdir -p /var/run /var/etc/xray','    :')
                init=self.root/'init';init.write_text(source);self.helper.chmod(0o755)
                tools=self.root/'tools';uci=tools/'uci';uci.write_text('#!/bin/sh\necho 1\n');uci.chmod(0o755)
                script='''. "$1"
config_load() { :; }
uci_get_by_type() { echo /bin/true; }
gen_config_file() { cat "$2"; }
start_xray() { echo STARTED; }
create_when_enable() { :; }
flush_when_disable() { echo CLEANED; }
# Functions have their own positional arguments, so bake the test path into a variable.
core_path=$2
gen_config_file() { cat "$core_path"; }
start_service
'''
                result=subprocess.run(['sh','-c',script,'_',str(init),str(self.core)],env=self.env,capture_output=True,text=True,timeout=5)
                if damaged:
                    self.assertNotEqual(result.returncode,0);self.assertIn('CLEANED',result.stdout);self.assertNotIn('STARTED',result.stdout)
                else:
                    self.assertEqual(result.returncode,0,result.stderr);self.assertIn('old-core',result.stdout);self.assertIn('STARTED',result.stdout)

    def test_truncated_manifest_is_rejected(self):
        self.command('prepare');self.mutate()
        (self.journal/'checksums').write_text('')
        self.command('recover',1);self.assertEqual(self.core.read_text(),'new-core')

if __name__=='__main__':unittest.main()
