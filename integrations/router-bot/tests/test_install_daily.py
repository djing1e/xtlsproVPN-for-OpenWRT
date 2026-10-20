import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]/'server'
spec = importlib.util.spec_from_file_location('install_daily_backup', BASE/'install-daily-backup.py')
i = importlib.util.module_from_spec(spec); spec.loader.exec_module(i)


class InstallDailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.app = self.root/'app/backup.py'; self.app.parent.mkdir()
        self.app.write_text('old helper')
        self.app.with_name('bot.py').write_text('running bot')
        self.config = self.root/'conf/config.json'; self.config.parent.mkdir()
        self.key = self.root/'sshkey'; self.key.write_text('private-key')
        self.hosts = self.root/'known_hosts'; self.hosts.write_text('pinned-hosts')
        self.config.write_text(json.dumps({'admin_id': 168179916, 'ssh_key': str(self.key), 'known_hosts': str(self.hosts)}))
        self.config.with_name('telegram_token').write_text('secret-token')
        self.config.with_name('backup.key').write_text('separate-recovery-key')
        self.units = self.root/'units'; self.units.mkdir()
        for name in [i.TIMER, i.SERVICE]: (self.units/name).write_text('old '+name)
        self.source = self.root/'new.py'; self.source.write_text((BASE/'backup.py').read_text())
        self.calls = []; self.bot_active = True; self.upload_return = 0
        self.patches = [patch.object(i, 'APP', self.app), patch.object(i, 'CONFIG', self.config),
                        patch.object(i, 'UNIT_DIR', self.units), patch.object(i.os, 'geteuid', return_value=0),
                        patch.object(i.subprocess, 'run', side_effect=self.run_command),
                        patch.object(i.tempfile, 'mkdtemp', side_effect=self.saved_dir)]
        for p in self.patches: p.start()

    def saved_dir(self, **kwargs):
        folder = self.root/'saved'; folder.mkdir(); return str(folder)

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        code = 0
        if args[:2] == ['systemctl', 'is-active']:
            code = 0 if (args[-1] == 'xtls-router-bot.service' and self.bot_active) or args[-1] == i.TIMER else 3
        if args == ['systemctl', 'start', i.SERVICE]: code = self.upload_return
        return types.SimpleNamespace(returncode=code)

    def configure(self):
        for name in [i.TIMER, i.SERVICE]: (self.units/name).write_text('new '+name)

    def test_update_preserves_bot_and_secrets_and_starts_delivery_not_bot(self):
        before = [p.read_bytes() for p in [self.config, self.key, self.hosts, self.config.with_name('telegram_token'), self.config.with_name('backup.key'), self.app.with_name('bot.py')]]
        with patch.object(i, 'configure_helper', side_effect=self.configure): i.install(self.source)
        self.assertEqual(self.app.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.app.stat().st_mode & 0o777, 0o644)
        self.assertNotIn(['systemctl', 'stop', 'xtls-router-bot.service'], self.calls)
        self.assertNotIn(['systemctl', 'restart', 'xtls-router-bot.service'], self.calls)
        self.assertIn(['systemctl', 'restart', i.TIMER], self.calls)
        self.assertIn(['systemctl', 'start', i.SERVICE], self.calls)
        self.assertEqual(before, [p.read_bytes() for p in [self.config, self.key, self.hosts, self.config.with_name('telegram_token'), self.config.with_name('backup.key'), self.app.with_name('bot.py')]])

    def test_unit_install_failure_restores_old_helper_units_and_timer(self):
        with patch.object(i, 'configure_helper', side_effect=RuntimeError('unit failed')):
            with self.assertRaises(RuntimeError): i.install(self.source)
        self.assertEqual(self.app.read_text(), 'old helper')
        self.assertEqual((self.units/i.TIMER).read_text(), 'old '+i.TIMER)
        self.assertIn(['systemctl', 'start', i.TIMER], self.calls)
        self.assertNotIn(['systemctl', 'start', i.SERVICE], self.calls)

    def test_inactive_test_copy_cannot_enable_uploads(self):
        self.bot_active = False
        with self.assertRaises(RuntimeError): i.install(self.source)
        self.assertEqual(self.app.read_text(), 'old helper')
        self.assertNotIn(['systemctl', 'enable', i.TIMER], self.calls)

    def test_network_failure_keeps_installed_retry_schedule(self):
        self.upload_return = 1
        with patch.object(i, 'configure_helper', side_effect=self.configure): i.install(self.source)
        self.assertEqual(self.app.read_bytes(), self.source.read_bytes())
        self.assertEqual((self.units/i.TIMER).read_text(), 'new '+i.TIMER)

if __name__ == '__main__': unittest.main()
