import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import test_telegram as pilot
import test_buttons as buttons

b, UID = pilot.b, pilot.UID
REQUEST = '11111111-2222-4333-8444-555555555555'
PLAN = '11111111-2222-4333-8444-555555555556'
BASE = Path(__file__).resolve().parents[1]


class UpdateBotTests(unittest.TestCase):
    callback = pilot.TelegramTests.callback
    messages = pilot.TelegramTests.messages
    tearDown = pilot.TelegramTests.tearDown
    button = buttons.ButtonFlowTests.button
    click = buttons.ButtonFlowTests.click

    def setUp(self):
        pilot.TelegramTests.setUp(self)
        self.plan = {'id': PLAN, 'component': 'app', 'installed': '1.0.0-r1', 'available': '1.1.0-r1', 'valid': True, 'update_available': True}
        self.job = {'id': REQUEST, 'component': 'app', 'action': 'check', 'state': 'done'}
        self.calls = []
        self.accepted = True
        def call(router, command, transport=None):
            self.calls.append((command, transport))
            if command == 'xtlsbot-v1 updates':
                return {'plans': [self.plan], 'job': dict(self.job)}
            if command.startswith(('xtlsbot-v1 update-check ', 'xtlsbot-v1 update-install ')):
                if not self.accepted:
                    raise b.SafeError('Ответ потерян')
                return {'accepted': True, 'id': REQUEST, 'action': self.job['action'], 'component': 'app'}
            if command == 'xtlsbot-v1 status':
                return {'running': True, 'proxy_ok': True}
            if command == 'xtlsbot-v1 admin-status':
                return {'netbird_connected': True}
            return {'nodes': []}
        self.bridge.call = call

    def run_op(self, action):
        self.job['action'] = action
        self.store.begin(42, UID, 'lab', action, '')
        self.bot.locks['lab'].acquire()
        with patch.object(b.uuid, 'uuid4', return_value=REQUEST), patch.object(b.time, 'sleep'), patch.object(self.bot, 'prepare_rescue') as rescue:
            self.bot.update_operation(UID, 'lab', 'app', action, PLAN, 42)
        return rescue

    def state(self):
        with self.store.connect() as db:
            return db.execute('SELECT state FROM operations WHERE update_id=42').fetchone()[0]

    def test_check_does_not_prepare_rescue_or_install(self):
        self.run_op('check').assert_not_called()
        self.assertEqual(self.state(), 'done')
        self.assertFalse(any('update-install' in command for command, _ in self.calls))

    def test_install_binds_exact_plan_and_rescue(self):
        self.run_op('install').assert_called_once_with(UID, 'lab')
        self.assertEqual(self.state(), 'done')
        self.assertIn(('xtlsbot-v1 update-install app ' + REQUEST + ' ' + PLAN, 'rescue'), self.calls)

    def test_lost_receipt_not_replayed(self):
        self.accepted = False
        self.run_op('install')
        self.assertEqual(self.state(), 'unconfirmed')
        self.assertEqual(sum('update-install' in cmd for cmd, _ in self.calls), 1)

    def test_failed_or_replaced_job_not_success(self):
        self.job['state'] = 'failed'
        self.run_op('check')
        self.assertEqual(self.state(), 'unconfirmed')

    def test_failed_settings_check_reports_reason_without_reinstall(self):
        self.job.update(state='failed', reason='settings')
        self.run_op('install')
        self.assertEqual(self.state(), 'unconfirmed')
        self.assertIn('Проверка сохранности настроек не пройдена.', str(self.messages()))
        self.assertEqual(sum('update-install' in cmd for cmd, _ in self.calls), 1)

    def test_client_cannot_invoke_update_callbacks_or_transport(self):
        client = 123456
        self.store.change_access(UID, client, 'lab', True)
        for action, target in [('updates', ''), ('update_check', 'app'), ('update_prompt', 'app:' + PLAN), ('update_install', 'app:' + PLAN)]:
            token = self.store.button(client, 'lab', action, target, self.store.grant_epoch(client, 'lab'))
            self.bot.handle(self.callback(token, uid=client))
        with self.assertRaises(b.SafeError):
            self.bot.router_call(client, 'lab', 'xtlsbot-v1 updates')
        self.assertEqual(self.calls, [])

    def test_prompt_requires_current_plan_and_cancel_invalidates(self):
        self.bot.update_prompt(UID, 'lab', 'app:' + PLAN)
        confirm = self.button('✅ Установить')
        self.bot.updates_menu(UID, 'lab')
        with patch.object(self.bot.pool, 'submit') as submit:
            self.bot.handle(self.callback(confirm))
            submit.assert_not_called()
        self.plan['valid'] = False
        with self.assertRaises(b.SafeError):
            self.bot.update_prompt(UID, 'lab', 'app:' + PLAN)

    def test_install_commands_forced_to_rescue_and_injection_rejected(self):
        router = {**self.config['routers']['lab'], 'rescue': {'host': '127.0.0.1', 'port': 22002}}
        result = SimpleNamespace(returncode=255, stdout=b'')
        with patch.object(b.subprocess, 'run', return_value=result) as run:
            with self.assertRaises(b.SafeError):
                b.Bridge(self.config).call(router, 'xtlsbot-v1 update-install app ' + REQUEST + ' ' + PLAN)
        self.assertEqual(run.call_count, 1)
        self.assertIn('root@127.0.0.1', run.call_args.args[0])
        for command in ('xtlsbot-v1 update-install app latest', 'xtlsbot-v1 update-check firmware ' + REQUEST, 'xtlsbot-v1 update-check app ' + REQUEST + ';id'):
            with patch.object(b.subprocess, 'run') as run:
                with self.assertRaises(b.SafeError):
                    b.Bridge(self.config).call(router, command)
                run.assert_not_called()


@unittest.skipUnless(shutil.which('ucode'), 'host ucode required')
class UpdatePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run'
        self.run.mkdir()
        self.bins = self.root / 'bin'
        self.bins.mkdir()
        self.installed = self.root / 'installed'
        self.installed.write_text('1.0.0-r1')
        self.boot = self.root / 'boot'
        self.boot.write_text(REQUEST)
        self.make(self.bins / 'apk', 'case "$1" in info) printf "xtlsprovpn-"; cat ' + str(self.installed) + ';; version) echo "<";; *) exit 1;; esac')
        self.env = dict(os.environ, PATH=str(self.bins) + ':' + os.environ['PATH'])
        text = (BASE / 'router/updates.uc').read_text().replace('/var/run/xtlspro-bot-updates', str(self.run)).replace('/var/run/xtlspro-package', str(self.root)).replace('/proc/sys/kernel/random/boot_id', str(self.boot))
        self.source = self.root / 'updates.uc'
        self.source.write_text(text)
        (self.root / 'catalog.json').write_text(json.dumps({'version': '1.1.0-r1', 'sha256': 'a'*64, 'checked': int(time.time()), 'url': 'SECRET-URL'}))

    def make(self, path, body):
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o700)

    def call(self, *args):
        result = subprocess.run(['ucode', str(self.source), *args], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertNotIn('SECRET', result.stdout)
        return result, json.loads(result.stdout) if result.stdout else None

    def test_plan_hides_urls_and_validates_exact_identity(self):
        result, plan = self.call('plan', 'app', PLAN)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(plan['update_available'])
        self.assertNotIn('digest', plan)
        self.assertEqual(self.call('validate', 'app', PLAN)[1], {'version': '1.1.0-r1', 'digest': 'a'*64})
        self.assertNotEqual(self.call('validate', 'app', REQUEST)[0].returncode, 0)

    def test_stale_boot_expiry_and_installed_change_refused(self):
        self.call('plan', 'app', PLAN)
        self.installed.write_text('1.0.1-r1')
        self.assertEqual(self.call('validate', 'app', PLAN)[1]['error'], 'installed_changed')
        self.installed.write_text('1.0.0-r1')
        path = self.run / 'app.json'
        plan = json.loads(path.read_text())
        plan['expires'] = 1
        path.write_text(json.dumps(plan))
        self.assertEqual(self.call('validate', 'app', PLAN)[1]['error'], 'plan_expired')
        self.boot.write_text(PLAN)
        self.assertFalse(self.call('status')[1]['plans'][0]['valid'])

    def test_missing_digest_or_shell_version_refused(self):
        path = self.root / 'catalog.json'
        for target, digest in [('1.1.0-r1', None), ('1.1.0-r1;id', 'a'*64)]:
            path.write_text(json.dumps({'version': target, 'sha256': digest, 'checked': int(time.time())}))
            self.assertNotEqual(self.call('plan', 'app', PLAN)[0].returncode, 0)

    def test_verify_requires_actual_installed_version(self):
        self.call('plan', 'app', PLAN)
        self.assertEqual(self.call('verify', 'app', PLAN)[1]['error'], 'version_mismatch')
        self.installed.write_text('1.1.0-r1')
        self.assertEqual(self.call('verify', 'app', PLAN)[0].returncode, 0)
        self.assertFalse(self.call('status')[1]['plans'][0]['update_available'])

    def test_native_patch_is_idempotent_and_refuses_unknown_layout(self):
        source = self.root / 'native.uc'
        output = self.root / 'patched.uc'
        source.write_text('function f(){\n    let c=package_catalog(true);\n}\n')
        self.assertEqual(self.call('patch-netbird', str(source), str(output))[0].returncode, 0)
        first = output.read_text()
        self.assertIn("getenv('FX_NETBIRD_EXPECTED_VERSION')", first)
        source.write_text(first)
        self.call('patch-netbird', str(source), str(output))
        self.assertEqual(output.read_text(), first)
        source.write_text('unknown layout')
        self.assertEqual(self.call('patch-netbird', str(source), str(output))[1]['error'], 'native_helper_changed')
