import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import unittest
import test_telegram as pilot

UID, JOB, b = pilot.UID, pilot.JOB, pilot.b

CLIENT = 123456789
OTHER = 234567890


class AccessTests(unittest.TestCase):
    callback = pilot.TelegramTests.callback
    messages = pilot.TelegramTests.messages
    tearDown = pilot.TelegramTests.tearDown
    def setUp(self):
        pilot.TelegramTests.setUp(self)
        self.config['routers']['home'] = {'name': 'PRIVATE-HOME', 'host': '100.124.0.2', 'port': 222}
        import threading
        self.bot.locks['home'] = threading.Lock()

    def message(self, uid, text):
        return {'update_id': 60, 'message': {'from': {'id': uid},
                'chat': {'id': uid, 'type': 'private'}, 'text': text}}

    def grant(self, uid=CLIENT, router='lab'):
        self.store.change_access(UID, uid, router, True)

    def token(self, uid, rid, action, target=''):
        return self.bot.button(uid, rid, action, action, target)['callback_data']

    def test_unbound_start_returns_only_own_id(self):
        self.bot.handle(self.message(CLIENT, '/start'))
        text = '\n'.join(self.messages())
        self.assertIn(str(CLIENT), text)
        self.assertNotIn('LAB', text)
        self.assertNotIn('PRIVATE-HOME', text)
        self.assertEqual(self.bridge.calls, [])

    def test_menu_client_only_sees_own_router(self):
        self.grant()
        self.bot.handle(self.message(CLIENT, '/start'))
        payload = self.tg.calls[-1][1]
        self.assertIn('LAB', json.dumps(payload))
        self.assertNotIn('PRIVATE-HOME', json.dumps(payload))
        self.assertEqual(self.bridge.calls, [])

    def test_client_can_switch_own_router_and_get_completion(self):
        self.grant()
        token = self.token(CLIENT, 'lab', 'select', 'cfg3db316')
        with patch.object(self.bot.pool, 'submit', side_effect=lambda fn, *args: fn(*args)):
            self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertEqual(self.bridge.calls[0], 'xtlsbot-v1 select cfg3db316')
        self.assertTrue(any('подтвердил применение' in m for m in self.messages()))
        self.assertFalse(self.bot.locks['lab'].locked())

    def test_admin_revoke_requires_confirmation_and_disables_old_status(self):
        self.grant()
        old = self.token(CLIENT, 'lab', 'status')
        self.bot.handle(self.message(UID, '/unbind lab ' + str(CLIENT)))
        self.assertIsNotNone(self.store.grant_epoch(CLIENT, 'lab'))
        token = self.tg.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
        self.bot.handle(self.callback(token))
        self.assertIsNone(self.store.grant_epoch(CLIENT, 'lab'))
        self.bot.handle(self.callback(old, uid=CLIENT))
        self.assertEqual(self.bridge.calls, [])

    def test_admin_can_see_all_routers(self):
        self.bot.menu(UID)
        self.assertIn('PRIVATE-HOME', json.dumps(self.tg.calls))

    def test_client_cannot_admin_even_with_own_callback(self):
        self.grant()
        self.bot.handle(self.message(CLIENT, '/bind home ' + str(CLIENT)))
        self.bot.handle(self.message(CLIENT, '/access home'))
        self.assertIsNone(self.store.grant_epoch(CLIENT, 'home'))
        self.assertNotIn('PRIVATE-HOME', '\n'.join(self.messages()))
        token = self.token(CLIENT, 'lab', 'grant', str(OTHER))
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertIsNone(self.store.grant_epoch(OTHER, 'lab'))
        token = self.token(CLIENT, 'lab', 'access')
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertNotIn(str(OTHER), '\n'.join(self.messages()))

    def test_admin_grant_requires_confirmation_and_is_one_use(self):
        self.bot.handle(self.message(UID, '/bind lab ' + str(CLIENT)))
        self.assertIsNone(self.store.grant_epoch(CLIENT, 'lab'))
        token = self.tg.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
        self.bot.handle(self.callback(token))
        self.assertIsNotNone(self.store.grant_epoch(CLIENT, 'lab'))
        before = len(self.store.clients('lab'))
        self.bot.handle(self.callback(token, update_id=99))
        self.assertEqual(len(self.store.clients('lab')), before)
        # No unsolicited message is sent to the newly enrolled customer.
        self.assertTrue(all(p.get('chat_id') != CLIENT for m, p in self.tg.calls if m == 'sendMessage'))

    def test_client_cannot_reuse_admin_confirmation(self):
        self.grant()
        self.bot.handle(self.message(UID, '/bind home ' + str(OTHER)))
        token = self.tg.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertIsNone(self.store.grant_epoch(OTHER, 'home'))

    def test_client_cannot_access_other_router_even_with_forged_stored_token(self):
        self.grant()
        token = self.store.button(CLIENT, 'home', 'status')
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertEqual(self.bridge.calls, [])
        self.assertNotIn('PRIVATE-HOME', '\n'.join(self.messages()))

    def test_revocation_invalidates_all_old_buttons_even_after_regrant(self):
        self.grant()
        token = self.token(CLIENT, 'lab', 'select', 'cfg3db316')
        epoch = self.store.grant_epoch(CLIENT, 'lab')
        self.store.change_access(UID, CLIENT, 'lab', False)
        self.grant()
        self.assertNotEqual(epoch, self.store.grant_epoch(CLIENT, 'lab'))
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertEqual(self.bridge.calls, [])

    def test_queued_worker_rechecks_epoch_after_regrant(self):
        self.grant()
        epoch = self.store.grant_epoch(CLIENT, 'lab')
        self.store.change_access(UID, CLIENT, 'lab', False)
        self.grant()
        self.bot.locks['lab'].acquire()
        self.bot.switch(CLIENT, 'lab', 'select', 'cfg3db316', 42, epoch)
        self.assertEqual(self.bridge.calls, [])
        self.assertFalse(self.bot.locks['lab'].locked())

    def test_revocation_during_job_stops_polling_and_disclosure(self):
        self.grant()
        epoch = self.store.grant_epoch(CLIENT, 'lab')
        original = self.bridge.call
        def accept_then_revoke(router, command):
            reply = original(router, command)
            self.store.change_access(UID, CLIENT, 'lab', False)
            return reply
        self.bridge.call = accept_then_revoke
        self.bot.locks['lab'].acquire()
        self.bot.switch(CLIENT, 'lab', 'auto', '', 42, epoch)
        self.assertEqual(self.bridge.calls, ['xtlsbot-v1 auto'])
        self.assertFalse(any('подтвердил применение' in m for m in self.messages()))

    def test_grants_survive_restart_without_admin_role_promotion(self):
        self.grant()
        epoch = self.store.grant_epoch(CLIENT, 'lab')
        self.bot.store = b.Store(self.store.path)
        self.assertEqual(self.bot.store.grant_epoch(CLIENT, 'lab'), epoch)
        self.assertEqual(self.bot.visible(CLIENT), {'lab'})
        with self.assertRaises(b.SafeError):
            self.bot.admin(CLIENT)

    def test_schema_migrates_existing_pilot_and_preserves_admin_buttons(self):
        path = Path(self.tmp.name) / 'legacy.db'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE buttons(token TEXT PRIMARY KEY,uid INTEGER,router TEXT,action TEXT,target TEXT,expires INTEGER,used INTEGER DEFAULT 0)')
            db.execute("INSERT INTO buttons VALUES ('old',?,'lab','status','',9999999999,0)", (UID,))
        migrated = b.Store(path)
        self.assertEqual(migrated.take_button('old', UID)['grant_epoch'], '')
        self.assertEqual(migrated.clients('lab'), [])

    def test_revoke_one_router_retains_other_grant(self):
        self.grant()
        self.grant(router='home')
        self.store.change_access(UID, CLIENT, 'lab', False)
        self.assertEqual(self.bot.visible(CLIENT), {'home'})
        token = self.token(CLIENT, 'home', 'status')
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertIn('xtlsbot-v1 status', self.bridge.calls)

    def test_invalid_admin_commands_never_change_grants(self):
        for text in ['/bind lab -1', '/bind lab 999999999999999999', '/bind lab 1;id', '/bind unknown 123',
                     '/bind lab ' + str(UID), '/unbind lab ' + str(UID)]:
            self.bot.handle(self.message(UID, text))
        self.assertEqual(self.store.clients('lab'), [])
