import json
import unittest
import test_telegram as fixtures
UID, b = fixtures.UID, fixtures.b


class CatalogTests(unittest.TestCase):
    setUp = fixtures.TelegramTests.setUp
    tearDown = fixtures.TelegramTests.tearDown
    callback = fixtures.TelegramTests.callback
    messages = fixtures.TelegramTests.messages

    def keyboard(self):
        return [p for m,p in self.tg.calls if m == 'sendMessage'][-1]['reply_markup']['inline_keyboard']

    def click(self, text):
        token = next(v['callback_data'] for row in self.keyboard() for v in row if v['text'] == text)
        self.bot.handle(self.callback(token))

    def text(self, value, uid=UID):
        self.bot.handle({'update_id': 50, 'message': {'from': {'id': uid}, 'chat': {'id': uid, 'type': 'private'}, 'text': value}})

    def fleet(self):
        for i in range(500):
            self.config['routers'][f'r{i:03}'] = {'name': f'Клиент {i:03}', 'host': '100.124.0.1', 'port': 22}

    def test_500_devices_bounded_pages_no_ssh_and_navigation(self):
        self.fleet()
        self.bot.menu(UID)
        self.assertIn('Найдено: 501 · Страница 1/51', self.messages()[-1])
        self.assertLessEqual(sum(map(len, self.keyboard())), 17)
        self.click('Вперёд ➡️')
        self.assertIn('Страница 2/51', self.messages()[-1])
        self.bot.menu(UID)
        self.assertIn('Страница 2/51', self.messages()[-1])
        self.assertEqual(self.bridge.calls, [])

    def test_search_hwid_normalized_subscription_and_reset(self):
        self.store.cache_hwid('lab', '242c-7c6d-ea5f-33d0')
        self.store.cache_subscription('lab', {'id': '1481'})
        self.bot.menu(UID)
        self.click('🔎 Поиск')
        self.text('242C7C6D')
        self.assertIn('Найдено: 1', self.messages()[-1])
        self.assertEqual(self.keyboard()[0][0]['text'], 'LAB')
        self.bot.menu(UID, query='№1481', page=0)
        self.assertIn('Найдено: 1', self.messages()[-1])
        self.text('/start')
        self.assertNotIn('Поиск:', self.messages()[-1])
        self.assertEqual(self.store.hwid('lab'), '242c-7c6d-ea5f-33d0')

    def test_client_search_does_not_leak_hidden_devices(self):
        self.fleet()
        with self.store.connect() as db:
            db.execute('INSERT INTO grants VALUES (?,?,?,?)', (123, 'lab', 'grant', 0))
        self.bot.menu(123, query='Клиент', page=0)
        self.assertIn('Найдено: 0', self.messages()[-1])
        self.assertFalse(any('Клиент 0' in v['text'] for row in self.keyboard() for v in row))
        self.bot.menu(123, query='', page=999)
        self.assertIn('Найдено: 1 · Страница 1/1', self.messages()[-1])

    def test_duplicate_names_use_real_hwid_and_card_keeps_full_hwid(self):
        self.config['routers']['other'] = dict(self.config['routers']['lab'])
        self.store.cache_hwid('lab', '242c-7c6d-ea5f-33d0')
        self.store.cache_hwid('other', 'abcd-1234-5678-9012')
        self.bot.menu(UID)
        labels = [v['text'] for row in self.keyboard() for v in row]
        self.assertIn('LAB · 242c-7c6d-ea5f-33d0', labels)
        self.assertIn('LAB · abcd-1234-5678-9012', labels)
        self.bot.status(UID, 'lab')
        self.assertTrue(self.messages()[-1].startswith('LAB · HWID 242c-7c6d-ea5f-33d0'))

    def test_empty_results_search_cancel_and_validation(self):
        self.bot.menu(UID, query='unknown', page=0)
        self.assertIn('Ничего не найдено', self.messages()[-1])
        self.click('🔎 Поиск')
        self.click('Отмена')
        self.assertFalse(self.store.catalog(UID)['awaiting'])
        for query,page in [('x'*101,0), ('line\nbreak',0), ('',True), ('',-1)]:
            with self.assertRaises(b.SafeError): self.bot.menu(UID, query, page)

    def test_stale_page_refilters_revoked_grant(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO grants VALUES (?,?,?,?)', (123, 'lab', 'old', 0))
        self.bot.menu(123)
        token = self.keyboard()[0][0]['callback_data']
        with self.store.connect() as db: db.execute('DELETE FROM grants WHERE uid=123')
        self.bot.handle(self.callback(token, uid=123))
        self.assertEqual(self.bridge.calls, [])

if __name__ == '__main__': unittest.main()
