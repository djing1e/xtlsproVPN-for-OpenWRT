import unittest
from unittest.mock import patch
import threading

import test_telegram as pilot

UID, b = pilot.UID, pilot.b
CLIENT = 123456789


class OperationsTests(unittest.TestCase):
    callback = pilot.TelegramTests.callback
    messages = pilot.TelegramTests.messages
    tearDown = pilot.TelegramTests.tearDown

    def setUp(self):
        pilot.TelegramTests.setUp(self)

    def test_ids_stable_and_models_can_match(self):
        self.assertEqual(self.store.router_code('lab'), 'R-000001')
        for _ in range(20):
            self.store.router_code('lab')
        self.assertEqual(self.store.router_code('another'), 'R-000002')
        code, _ = self.store.user_info(CLIENT, 'First client')
        for _ in range(20):
            self.store.user_info(CLIENT)
        self.assertEqual(self.store.user_info(987654321)[0], 'U-000002')
        restarted = b.Store(self.store.path)
        self.assertEqual(restarted.user_info(CLIENT)[0], code)
        self.assertEqual(restarted.router_code('another'), 'R-000002')

    def test_bind_by_user_code_and_precise_confirmation(self):
        code, _ = self.store.user_info(CLIENT, 'Customer')
        self.bot.access_prompt(UID, 'lab', code, True)
        text = self.messages()[-1]
        self.assertIn('Customer', text)
        self.assertIn(str(CLIENT), text)
        self.assertIn('LAB', text)
        self.assertIsNone(self.store.grant_epoch(CLIENT, 'lab'))

    def test_grant_and_revoke_notifications_with_button(self):
        self.store.change_access(UID, CLIENT, 'lab', True)
        self.bot.deliver_notifications()
        sent = [p for m, p in self.tg.calls if m == 'sendMessage' and p['chat_id'] == CLIENT]
        self.assertIn('Доступ выдан', sent[0]['text'])
        self.assertIn('Открыть роутер', str(sent[0]['reply_markup']))
        self.store.change_access(UID, CLIENT, 'lab', False)
        self.bot.deliver_notifications()
        self.assertIn('Доступ отозван', self.messages()[-1])
        self.assertEqual(self.store.pending_notifications(), [])

    def test_old_grant_notification_not_sent_after_revocation(self):
        self.store.change_access(UID, CLIENT, 'lab', True)
        self.store.change_access(UID, CLIENT, 'lab', False)
        self.bot.deliver_notifications()
        self.assertFalse(any('Доступ выдан' in m for m in self.messages()))
        self.assertTrue(any('Доступ отозван' in m for m in self.messages()))

    def test_blocked_notification_reported_to_admin_without_undoing_grant(self):
        self.store.change_access(UID, CLIENT, 'lab', True)
        original = self.tg.call
        def send(method, **args):
            if args.get('chat_id') == CLIENT:
                raise b.SafeError('blocked', 403)
            return original(method, **args)
        self.tg.call = send
        self.bot.deliver_notifications()
        self.assertIsNotNone(self.store.grant_epoch(CLIENT, 'lab'))
        self.assertTrue(any('не доставлено' in m for m in self.messages()))
        self.assertEqual(self.store.pending_notifications(), [])

    def test_network_notification_failure_remains_retryable(self):
        self.store.change_access(UID, CLIENT, 'lab', True)
        with patch.object(self.tg, 'call', side_effect=b.SafeError('network')):
            self.bot.deliver_notifications()
        with self.store.connect() as db:
            row = db.execute('SELECT state,retry_at FROM notifications').fetchone()
        self.assertEqual(row[0], 'pending')
        self.assertGreater(row[1], 0)

    def test_duplicate_read_token_never_dispatches_twice_or_spams_chat(self):
        token = self.store.button(UID, 'lab', 'status')
        self.bot.handle(self.callback(token))
        before = len(self.messages())
        self.bot.handle(self.callback(token, update_id=43))
        self.assertEqual(self.bridge.calls.count('xtlsbot-v1 status'), 1)
        self.assertEqual(len(self.messages()), before)

    def test_busy_async_read_rejects_new_click_and_eventually_releases(self):
        submitted = []
        self.bot.submit_read = b.Bot.submit_read.__get__(self.bot)
        token1 = self.store.button(UID, 'lab', 'status')
        token2 = self.store.button(UID, 'lab', 'locations')
        with patch.object(self.bot.pool, 'submit', side_effect=lambda fn: submitted.append(fn)):
            self.bot.handle(self.callback(token1))
            self.bot.handle(self.callback(token2, update_id=43))
        self.assertEqual(len(submitted), 1)
        self.assertEqual(self.bridge.calls, [])
        submitted[0]()
        self.assertNotIn(UID, self.bot.read_busy)
        self.assertEqual(self.bridge.calls.count('xtlsbot-v1 status'), 1)

    def test_id_only_is_not_authorization(self):
        code = self.store.user_info(CLIENT)[0]
        self.assertFalse(self.bot.visible(CLIENT))
        with self.assertRaises(b.SafeError):
            self.bot.authorize(CLIENT, 'lab')
