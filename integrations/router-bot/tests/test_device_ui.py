import unittest
from pathlib import Path
import test_catalog as catalog
from test_telegram import UID, b


class DeviceUI(unittest.TestCase):
    setUp = catalog.CatalogTests.setUp
    tearDown = catalog.CatalogTests.tearDown
    callback = catalog.CatalogTests.callback
    messages = catalog.CatalogTests.messages
    keyboard = catalog.CatalogTests.keyboard
    click = catalog.CatalogTests.click
    text = catalog.CatalogTests.text

    def test_rename_persists_and_search_uses_new_name_without_changing_identity(self):
        self.store.change_access(UID, 123, 'lab', True)
        self.bot.admin_menu(UID, 'lab')
        self.click('✏️ Переименовать')
        self.text('Клиент 12426 · Москва')
        self.assertIn('Имя сохранено: Клиент 12426 · Москва', self.messages()[-1])
        self.assertEqual(self.config['routers']['lab']['name'], 'LAB')
        restarted = b.Bot(self.config, self.tg, b.Store(self.store.path), self.bridge)
        try:
            self.assertTrue(restarted.router_label('lab').startswith('Клиент 12426 · Москва'))
            restarted.menu(123, query='Москва', page=0)
            self.assertIn('Найдено: 1', self.messages()[-1])
            self.assertEqual(self.keyboard()[0][0]['text'], '⚪ Клиент 12426 · Москва')
            self.assertTrue(self.store.grant_epoch(123, 'lab'))
            self.assertEqual(self.bridge.calls, [])
        finally:
            restarted.pool.shutdown(wait=True)

    def test_client_cannot_rename_with_forged_callback(self):
        self.store.change_access(UID, 123, 'lab', True)
        token = self.bot.button(123, 'lab', 'rename', 'rename_prompt')['callback_data']
        self.bot.handle(self.callback(token, uid=123))
        self.assertIsNone(self.store.operator_dialog(123))
        self.assertEqual(self.bot.router_name('lab'), 'LAB')

    def test_rename_validation_cancel_and_expired_dialog(self):
        self.bot.admin_menu(UID, 'lab')
        self.click('✏️ Переименовать')
        self.text('x' * 81)
        self.assertEqual(self.bot.router_name('lab'), 'LAB')
        self.assertEqual(self.store.operator_dialog(UID)['stage'], 'rename')
        self.text('/start')
        self.text('Accidental name')
        self.assertEqual(self.bot.router_name('lab'), 'LAB')
        self.store.operator_dialog(UID, 'rename', 'lab')
        with self.store.connect() as db:
            db.execute('UPDATE operator_dialogs SET expires=0')
        self.text('Expired name')
        self.assertEqual(self.bot.router_name('lab'), 'LAB')
        for name in ('', '   ', 'bad\nname', 'bad\tname', 'x' * 81):
            with self.assertRaises(b.SafeError):
                self.store.rename_router(UID, 'lab', name)

    def test_support_url_in_catalog_card_help_and_without_access(self):
        self.store.change_access(UID, 123, 'lab', True)
        for action in (lambda: self.bot.menu(123), lambda: self.bot.status(123, 'lab'),
                       lambda: self.bot.help(123), lambda: self.text('/start', uid=456)):
            action()
            links = [v.get('url') for row in self.keyboard() for v in row]
            self.assertIn('https://t.me/xtlsprosupportbot', links)

    def test_status_displays_reported_version_or_unknown(self):
        self.bridge.call = lambda router, command: {'version': '1.4.1-r1'} if command.endswith('status') else {}
        self.bot.status(UID, 'lab')
        self.assertIn('Версия: 1.4.1-r1', self.messages()[-1])
        self.bridge.call = lambda router, command: {'version': None}
        self.bot.status(UID, 'lab')
        self.assertIn('Версия: нет данных', self.messages()[-1])
