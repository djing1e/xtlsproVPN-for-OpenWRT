import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'server/bot.py'
spec = importlib.util.spec_from_file_location('router_telegram', SOURCE)
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

UID = 168179916
JOB = '8447142f-da8f-4b03-8f2a-337cded6e084'


class TelegramFake:
    def __init__(self):
        self.calls = []

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        return {}


class BridgeFake:
    def __init__(self):
        self.calls = []
        self.job_state = 'done'
        self.job_id = JOB

    def call(self, router, command):
        self.calls.append(command)
        if command == 'xtlsbot-v1 status':
            return {'mode': 'manual', 'selected': ['cfg3db316'], 'running': True, 'proxy_ok': True}
        if command == 'xtlsbot-v1 locations':
            return {'nodes': [{'id': 'cfg3db316', 'name': 'Швейцария', 'selected': True}]}
        if command.startswith('xtlsbot-v1 job '):
            return {'job': {'id': self.job_id, 'state': self.job_state}}
        return {'accepted': True, 'job': {'id': JOB, 'state': 'pending'}}


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'admin_id': UID, 'ssh_key': '/key', 'known_hosts': '/known',
                       'routers': {'lab': {'name': 'LAB', 'host': '100.124.249.61', 'port': 22}}}
        self.store = b.Store(Path(self.tmp.name) / 'db')
        self.tg, self.bridge = TelegramFake(), BridgeFake()
        self.bot = b.Bot(self.config, self.tg, self.store, self.bridge)
        # Deterministic UI tests; separate operations tests exercise real scheduling.
        self.bot.submit_read = lambda uid, rid, action, epoch: (self.bot.status if action == 'status' else self.bot.locations)(uid, rid, epoch)

    def tearDown(self):
        self.bot.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def callback(self, token, uid=UID, chat_type='private', update_id=42):
        return {'update_id': update_id, 'callback_query': {'id': 'q', 'from': {'id': uid}, 'data': token,
                'message': {'chat': {'id': uid, 'type': chat_type}}}}

    def messages(self):
        return [payload['text'] for method, payload in self.tg.calls if method == 'sendMessage']

    def test_unauthorized_user_and_group_cannot_contact_router(self):
        token = self.store.button(UID, 'lab', 'select', 'cfg3db316')
        self.bot.handle(self.callback(token, uid=123))
        self.bot.handle(self.callback(token, chat_type='group'))
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.messages(), [])

    def test_callback_bound_to_user_and_expiry(self):
        token = self.store.button(UID, 'lab', 'select', 'cfg3db316')
        with self.assertRaises(b.SafeError):
            self.store.take_button(token, 123)
        with patch.object(b.time, 'time', return_value=b.time.time() + 1000):
            with self.assertRaises(b.SafeError):
                self.store.take_button(token, UID)

    def test_mutating_button_one_use(self):
        token = self.store.button(UID, 'lab', 'auto')
        self.store.take_button(token, UID)
        with self.assertRaises(b.SafeError):
            self.store.take_button(token, UID)

    def test_every_callback_checks_current_access(self):
        token = self.store.button(UID, 'lab', 'select', 'cfg3db316')
        self.config['admin_id'] = 123
        self.bot.handle(self.callback(token))
        self.assertEqual(self.bridge.calls, [])

    def test_unknown_router_rejected(self):
        token = self.store.button(UID, 'missing', 'select', 'cfg3db316')
        self.bot.handle(self.callback(token))
        self.assertEqual(self.bridge.calls, [])

    def test_duplicate_update_never_replays_after_restart(self):
        self.assertTrue(self.store.begin(42, UID, 'lab', 'auto', ''))
        restarted = b.Store(self.store.path)
        self.assertFalse(restarted.begin(42, UID, 'lab', 'auto', ''))
        with restarted.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM operations').fetchone()[0], 'interrupted')

    def test_matching_done_required_before_success(self):
        self.store.begin(42, UID, 'lab', 'select', 'cfg3db316')
        self.bot.locks['lab'].acquire()
        self.bot.switch(UID, 'lab', 'select', 'cfg3db316', 42)
        self.assertIn('xtlsbot-v1 job ' + JOB, self.bridge.calls)
        self.assertTrue(any('подтвердил применение' in m for m in self.messages()))
        self.assertFalse(self.bot.locks['lab'].locked())
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM operations').fetchone()[0], 'done')

    def test_replaced_or_failed_job_is_not_success(self):
        for job_id, state in [(JOB, 'failed'), ('00000000-0000-0000-0000-000000000000', 'done')]:
            self.tg.calls.clear()
            self.bridge.job_id, self.bridge.job_state = job_id, state
            self.bot.locks['lab'].acquire()
            self.bot.switch(UID, 'lab', 'auto', '', 42)
            self.assertFalse(any('подтвердил применение' in m for m in self.messages()))

    def test_timeout_does_not_claim_success(self):
        self.bridge.job_state = 'running'
        self.bot.locks['lab'].acquire()
        with patch.object(b.time, 'monotonic', side_effect=[0, 91]):
            self.bot.switch(UID, 'lab', 'auto', '', 42)
        self.assertTrue(any('не подтверждён' in m for m in self.messages()))

    def test_router_lock_rejects_concurrent_mutation(self):
        token = self.store.button(UID, 'lab', 'auto')
        self.bot.locks['lab'].acquire()
        self.bot.handle(self.callback(token))
        self.bot.locks['lab'].release()
        self.assertEqual(self.bridge.calls, [])
        self.assertTrue(any('уже выполняется' in m for m in self.messages()))

    def test_status_and_location_buttons(self):
        for action in ('status', 'locations'):
            token = self.store.button(UID, 'lab', action)
            self.bot.handle(self.callback(token))
        self.assertTrue(any('Швейцария' in m for m in self.messages()))
        self.assertFalse(any('100.124.' in m for m in self.messages()))

    def test_ssh_options_and_shell_injection_rejected(self):
        args = b.ssh_command(self.config, self.config['routers']['lab'], 'xtlsbot-v1 status')
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('PreferredAuthentications=publickey', args)
        self.assertNotIn('shell=True', args)
        with patch.object(b.subprocess, 'run') as run:
            with self.assertRaises(b.SafeError):
                b.Bridge(self.config).call(self.config['routers']['lab'], 'xtlsbot-v1 auto; id')
            run.assert_not_called()

    def test_ssh_error_contents_not_exposed(self):
        class Result:
            returncode = 255
            stdout = b''
            stderr = b'SECRET ENDPOINT TOKEN'
        with patch.object(b.subprocess, 'run', return_value=Result()):
            with self.assertRaises(b.SafeError) as error:
                b.Bridge(self.config).call(self.config['routers']['lab'], 'xtlsbot-v1 status')
        self.assertNotIn('SECRET', str(error.exception))

    def test_token_url_not_exposed_in_errors(self):
        tg = b.Telegram('123:SECRET')
        with patch.object(tg.opener, 'open', side_effect=OSError('https://api.telegram.org/bot123:SECRET')):
            with self.assertRaises(b.SafeError) as error:
                tg.call('getMe')
        self.assertNotIn('SECRET', str(error.exception))

    def test_offset_never_moves_backwards(self):
        self.store.checkpoint(50)
        self.store.checkpoint(10)
        self.assertEqual(self.store.offset(), 51)


if __name__ == '__main__':
    unittest.main()
