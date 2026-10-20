import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_telegram as pilot

spec = importlib.util.spec_from_file_location('bot_upgrade', Path(__file__).resolve().parents[1] / 'server/upgrade.py')
upgrade = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'bot': pilot.b}):
    spec.loader.exec_module(upgrade)


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = self.root / 'installed.py'
        self.app.write_text('# old application\n')
        self.source = self.root / 'download'
        self.source.mkdir()
        (self.source / 'bot.py').write_text('# new application\n')
        self.key, self.known, self.token = [self.root / name for name in ('key', 'known', 'token')]
        for path in (self.key, self.known, self.token):
            path.write_text('PRESERVED ' + path.name)
        self.db = self.root / 'state.sqlite3'
        self.store = pilot.b.Store(self.db)
        self.store.change_access(1, 2, 'lab', True)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'admin_id': 1, 'bot_username': 'xtlsproroutbot',
            'ssh_key': str(self.key), 'known_hosts': str(self.known), 'database': str(self.db),
            'routers': {'lab': {'name': 'LAB', 'host': '100.124.0.1', 'port': 22}}}))
        self.before = {p: p.read_bytes() for p in (self.config, self.key, self.known, self.token)}
        self.commands = []
        self.backup = self.root / 'backup'
        def backup(**kwargs):
            self.backup.mkdir()
            return str(self.backup)
        self.patchers = [patch.object(upgrade, 'APP', self.app), patch.object(upgrade, 'CONFIG', self.config),
                         patch.object(upgrade, 'TOKEN', self.token),
                         patch.object(upgrade, '__file__', str(self.source / 'upgrade.py')),
                         patch.object(upgrade.os, 'geteuid', return_value=0),
                         patch.object(upgrade.tempfile, 'mkdtemp', side_effect=backup),
                         patch.object(upgrade.time, 'sleep'),
                         patch.object(upgrade, 'command', side_effect=lambda *args: self.commands.append(args))]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.tmp.cleanup()

    def test_update_preserves_identity_token_config_and_grants(self):
        upgrade.main()
        self.assertEqual(self.app.read_text(), '# new application\n')
        for path, content in self.before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.store.clients('lab'), [2])
        with sqlite3.connect(str(self.backup / 'bot.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual((self.backup / 'bot.py').read_text(), '# old application\n')

    def test_busy_update_never_stops_service(self):
        self.store.begin(42, 2, 'lab', 'auto', '')
        with self.assertRaises(pilot.b.SafeError):
            upgrade.main()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.app.read_text(), '# old application\n')

    def test_migration_failure_keeps_old_app_and_restarts_service(self):
        with patch.object(upgrade, 'Store', side_effect=ValueError('migration')):
            with self.assertRaises(ValueError):
                upgrade.main()
        self.assertEqual(self.app.read_text(), '# old application\n')
        self.assertEqual(self.commands[-1], ('start', 'xtls-router-bot'))

    def test_start_failure_rolls_back_code_without_rewinding_grants(self):
        started = False
        def command(*args):
            nonlocal started
            self.commands.append(args)
            if args[0] == 'start' and not started:
                started = True
                self.store.change_access(1, 3, 'lab', True)
                raise OSError('start failed')
        with patch.object(upgrade, 'command', side_effect=command):
            with self.assertRaises(OSError):
                upgrade.main()
        self.assertEqual(self.app.read_text(), '# old application\n')
        self.assertEqual(self.store.clients('lab'), [2, 3])

    def test_state_symlink_refused_before_service_change(self):
        original = self.root / 'db-target'
        self.db.rename(original)
        self.db.symlink_to(original)
        with self.assertRaises(pilot.b.SafeError):
            upgrade.main()
        self.assertEqual(self.commands, [])
