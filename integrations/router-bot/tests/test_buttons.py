import unittest
from unittest.mock import patch

import test_telegram as pilot

UID, b = pilot.UID, pilot.b
CLIENT = 123456789


class ButtonFlowTests(unittest.TestCase):
    callback = pilot.TelegramTests.callback
    messages = pilot.TelegramTests.messages
    tearDown = pilot.TelegramTests.tearDown

    def setUp(self):
        pilot.TelegramTests.setUp(self)

    def message(self, text, uid=UID):
        return {'update_id': 100, 'message': {'from': {'id': uid},
                'chat': {'id': uid, 'type': 'private'}, 'text': text}}

    def button(self, text):
        for method, payload in reversed(self.tg.calls):
            for row in payload.get('reply_markup', {}).get('inline_keyboard', []):
                for button in row:
                    if button['text'] == text or button['text'].endswith(' · ' + text) or button['text'].startswith(text+' · HWID '):
                        return button['callback_data']
        self.fail('Button missing: ' + text)

    def click(self, text, uid=UID):
        self.bot.handle(self.callback(self.button(text), uid=uid))

    def test_button_enrollment_end_to_end_requires_confirmation(self):
        self.bot.handle(self.message('/start'))
        self.click('LAB')
        self.click('👥 Доступ клиентов')
        self.click('➕ Добавить клиента')
        self.assertEqual(self.store.dialog(UID), 'lab')
        self.bot.handle(self.message(str(CLIENT)))
        self.assertIsNone(self.store.grant_epoch(CLIENT, 'lab'))
        self.assertIsNone(self.store.dialog(UID))
        self.click('Подтвердить')
        self.assertIsNotNone(self.store.grant_epoch(CLIENT, 'lab'))
        self.assertEqual(self.bridge.calls, ['xtlsbot-v1 status', 'xtlsbot-v1 locations'])

    def test_invalid_id_retains_dialog_without_grant(self):
        self.bot.grant_input(UID, 'lab')
        for text in ['@username', '-1', '123; id', '9999999999999999999']:
            self.bot.handle(self.message(text))
        self.assertEqual(self.store.dialog(UID), 'lab')
        self.assertEqual(self.store.clients('lab'), [])
        self.assertEqual(self.bridge.calls, [])

    def test_cancel_input_then_numeric_text_does_not_create_confirmation(self):
        self.bot.grant_input(UID, 'lab')
        self.click('Отмена')
        self.assertIsNone(self.store.dialog(UID))
        self.bot.handle(self.message(str(CLIENT)))
        self.assertEqual(self.store.clients('lab'), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM buttons WHERE action='grant'").fetchone()[0], 0)

    def test_cancel_confirmation_invalidates_old_confirm_button(self):
        self.bot.grant_input(UID, 'lab')
        self.bot.handle(self.message(str(CLIENT)))
        confirm = self.button('Подтвердить')
        self.click('Отмена')
        self.bot.handle(self.callback(confirm))
        self.assertIsNone(self.store.grant_epoch(CLIENT, 'lab'))

    def test_expired_input_does_not_create_grant(self):
        self.bot.grant_input(UID, 'lab')
        with patch.object(b.time, 'time', return_value=b.time.time() + 601):
            self.bot.handle(self.message(str(CLIENT)))
        self.assertIsNone(self.store.grant_epoch(CLIENT, 'lab'))
        self.assertIsNone(self.store.dialog(UID))

    def test_client_cannot_start_admin_dialog(self):
        self.store.change_access(UID, CLIENT, 'lab', True)
        epoch = self.store.grant_epoch(CLIENT, 'lab')
        token = self.store.button(CLIENT, 'lab', 'grant_input', grant_epoch=epoch)
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertIsNone(self.store.dialog(CLIENT))
        self.assertEqual(self.bridge.calls, [])

    def test_navigation_and_help_buttons_without_commands(self):
        self.bot.menu(UID)
        self.click('🆔 Мой ID')
        self.assertIn(str(UID), self.messages()[-1])
        self.click('ℹ️ Помощь')
        self.click('🏠 Мои роутеры')
        self.click('LAB')
        self.click('🏠 Мои роутеры')
        self.assertIn('Выберите роутер', self.messages()[-1])

    def test_other_callback_cancels_pending_input(self):
        self.bot.menu(UID)
        menu = self.button('ℹ️ Помощь')
        self.bot.grant_input(UID, 'lab')
        self.bot.handle(self.callback(menu))
        self.assertIsNone(self.store.dialog(UID))

    def test_input_survives_restart_only_for_its_admin(self):
        self.bot.grant_input(UID, 'lab')
        self.bot.store = b.Store(self.store.path)
        self.assertEqual(self.bot.store.dialog(UID), 'lab')
        self.bot.handle(self.message(str(CLIENT), uid=CLIENT))
        self.assertIsNone(self.bot.store.grant_epoch(CLIENT, 'lab'))
        self.bot.handle(self.message(str(CLIENT)))
        self.click('Подтвердить')
        self.assertIsNotNone(self.bot.store.grant_epoch(CLIENT, 'lab'))
