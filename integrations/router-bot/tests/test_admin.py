import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_telegram as pilot
import test_buttons as buttons

b, UID = pilot.b, pilot.UID
BOOT = '00000000-0000-4000-8000-000000000001'
NEW_BOOT = '00000000-0000-4000-8000-000000000002'
REQUEST = '00000000-0000-4000-8000-000000000003'


class AdminTests(unittest.TestCase):
    callback = pilot.TelegramTests.callback
    messages = pilot.TelegramTests.messages
    tearDown = pilot.TelegramTests.tearDown
    button = buttons.ButtonFlowTests.button
    click = buttons.ButtonFlowTests.click

    def setUp(self):
        pilot.TelegramTests.setUp(self)
        self.calls = []
        self.current = {'boot_id': BOOT, 'netbird_enabled': True, 'rescue_ready': True, 'netbird_connected': True}
        self.status = {'running': True, 'proxy_ok': True, 'health_checked': 100}
        self.mutation_lost = False
        self.job_state = 'done'
        self.action = 'netbird'
        def call(router, command, transport=None):
            self.calls.append((command, transport))
            if command == 'xtlsbot-v1 admin-open-rescue':
                return {'ok': True}
            if command == 'xtlsbot-v1 admin-status':
                return dict(self.current)
            if command.startswith('xtlsbot-v1 admin '):
                if self.mutation_lost:
                    raise b.SafeError('Ответ потерян')
                self.current = {**self.current, 'job': {'id': REQUEST, 'action': self.action, 'state': self.job_state}}
                if self.action == 'reboot':
                    self.current['boot_id'] = NEW_BOOT
                return {'accepted': True, 'id': REQUEST, 'action': self.action, 'boot_id': BOOT}
            if command == 'xtlsbot-v1 status':
                return dict(self.status)
            return {'nodes': []}
        self.bridge.call = call

    def run_operation(self, action):
        self.action = action
        self.store.begin_admin(42, UID, 'lab', action)
        self.bot.locks['lab'].acquire()
        with patch.object(b.uuid, 'uuid4', return_value=REQUEST), patch.object(b.time, 'sleep'):
            self.bot.admin_operation(UID, 'lab', action, 42)

    def state(self):
        with self.store.connect() as db:
            return db.execute('SELECT state FROM operations WHERE update_id=42').fetchone()[0]

    def test_netbird_dispatch_and_verification(self):
        self.run_operation('netbird')
        self.assertEqual(self.state(), 'done')
        self.assertIn(('xtlsbot-v1 admin netbird ' + REQUEST, 'rescue'), self.calls)
        self.assertIn(('xtlsbot-v1 status', 'netbird'), self.calls)

    def test_proxy_checks_health(self):
        self.run_operation('proxy')
        self.assertEqual(self.state(), 'done')
        self.assertTrue(any('HTTPS успешна' in text for text in self.messages()))

    def test_reboot_requires_changed_boot_and_health(self):
        self.run_operation('reboot')
        self.assertEqual(self.state(), 'done')
        self.assertTrue(any('Новая загрузка' in text for text in self.messages()))

    def test_no_success_when_job_failed(self):
        self.job_state = 'failed'
        self.run_operation('proxy')
        self.assertEqual(self.state(), 'unconfirmed')

    def test_lost_mutation_is_not_replayed(self):
        self.mutation_lost = True
        self.run_operation('netbird')
        self.assertEqual(self.state(), 'unconfirmed')
        self.assertEqual(sum(command.startswith('xtlsbot-v1 admin ') for command, transport in self.calls), 1)
        self.assertFalse(self.bot.locks['lab'].locked())

    def test_preflight_failure_never_dispatches(self):
        self.current['rescue_ready'] = False
        self.run_operation('reboot')
        self.assertEqual(self.state(), 'unconfirmed')
        self.assertFalse(any(command.startswith('xtlsbot-v1 admin ') for command, transport in self.calls))

    def test_clients_cannot_forge_admin_buttons_or_dispatch(self):
        client = 12345
        self.store.change_access(UID, client, 'lab', True)
        for action in ('admin_menu', 'admin_prompt', 'admin_confirm', 'admin_reboot_confirm'):
            token = self.store.button(client, 'lab', action, 'reboot', self.store.grant_epoch(client, 'lab'))
            self.bot.handle(self.callback(token, uid=client))
        with self.assertRaises(b.SafeError):
            self.bot.router_call(client, 'lab', 'xtlsbot-v1 admin-status')
        self.assertEqual(self.calls, [])

    def test_cancel_invalidates_confirmation_and_reboot_needs_second_confirm(self):
        self.bot.admin_prompt(UID, 'lab', 'netbird')
        confirm = self.button('✅ Подтвердить')
        self.click('Отмена')
        self.bot.handle(self.callback(confirm))
        self.assertEqual(self.calls, [])
        self.bot.admin_prompt(UID, 'lab', 'reboot')
        with patch.object(self.bot.pool, 'submit') as submit:
            self.click('✅ Подтвердить')
            submit.assert_not_called()
            self.click('✅ Подтвердить')
            self.assertEqual(submit.call_count, 1)
        self.bot.locks['lab'].release()

    def test_duplicate_and_cross_action_cooldown(self):
        self.assertTrue(self.store.begin_admin(100, UID, 'lab', 'proxy'))
        self.store.finish(100, 'done')
        with self.assertRaises(b.SafeError):
            self.store.begin_admin(101, UID, 'lab', 'netbird')
        with patch.object(b.time, 'time', return_value=b.time.time() + 301):
            self.assertTrue(self.store.begin_admin(102, UID, 'lab', 'netbird'))

    def test_no_success_from_stale_boot_or_failed_health(self):
        self.status['proxy_ok'] = False
        with patch.object(b.time, 'monotonic', side_effect=[0, 1, 301]):
            self.run_operation('reboot')
        self.assertEqual(self.state(), 'unconfirmed')
        self.assertFalse(any('Перезагрузка подтверждена.' in text for text in self.messages()))

    def test_new_recovery_opens_closed_reserve_through_primary_once(self):
        original = self.bridge.call
        first = True
        def call(router, command, transport=None):
            nonlocal first
            if command == 'xtlsbot-v1 admin-status' and first:
                first = False
                raise b.TransportError('Unavailable')
            return original(router, command, transport)
        self.bridge.call = call
        self.run_operation('proxy')
        self.assertEqual(self.state(), 'done')
        self.assertEqual(self.calls.count(('xtlsbot-v1 admin-open-rescue', 'netbird')), 1)

    def test_bridge_admin_never_uses_primary_or_replays(self):
        router = {**self.config['routers']['lab'], 'rescue': {'host': '127.0.0.1', 'port': 22002}}
        result = SimpleNamespace(returncode=255, stdout=b'')
        with patch.object(b.subprocess, 'run', return_value=result) as run:
            with self.assertRaises(b.SafeError):
                b.Bridge(self.config).call(router, 'xtlsbot-v1 admin netbird ' + REQUEST)
        self.assertEqual(run.call_count, 1)
        self.assertIn('root@127.0.0.1', run.call_args.args[0])
        with patch.object(b.subprocess, 'run') as run:
            with self.assertRaises(b.SafeError):
                b.Bridge(self.config).call(self.config['routers']['lab'], 'xtlsbot-v1 admin reboot ' + REQUEST)
            run.assert_not_called()
