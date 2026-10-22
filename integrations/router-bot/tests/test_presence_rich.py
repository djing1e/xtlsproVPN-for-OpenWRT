import json
import time
import unittest
from unittest.mock import patch
import test_telegram as fixtures
from test_telegram import UID, b


class PresenceRich(unittest.TestCase):
    setUp = fixtures.TelegramTests.setUp
    tearDown = fixtures.TelegramTests.tearDown

    def last(self, method='sendMessage'):
        return [p for m, p in self.tg.calls if m == method][-1]

    def test_cached_catalog_never_probes_and_counts_only_visible_routers(self):
        self.config['routers']['hidden'] = {'name': 'PRIVATE', 'host': '100.124.0.2', 'port': 22}
        now = time.time()
        self.store.presence_result('lab', True, now, 'rescue')
        self.store.presence_result('hidden', False, now)
        self.store.change_access(UID, 123, 'lab', True)
        self.bot.menu(123)
        p = self.last()
        self.assertIn('В сети: 1', p['text'])
        self.assertIn('Нет связи: 0', p['text'])
        self.assertEqual(p['reply_markup']['inline_keyboard'][0][0]['text'], '🟢 LAB')
        self.assertNotIn('PRIVATE', json.dumps(p))
        self.assertEqual(self.bridge.calls, [])
        self.store.presence_result('lab', False, time.time())
        self.bot.menu(123)
        self.assertIn('Нет связи: 1', self.last()['text'])

    def test_stale_unknown_and_future_clock_are_not_online(self):
        for record in (None, {'checked': 1, 'reachable': 1}, {'checked': 1000, 'reachable': 1}):
            self.assertEqual(self.bot.presence_view(record, now=500)[0], 'unknown')
        self.assertEqual(self.bot.presence_view({'checked': 400, 'reachable': 0}, now=500)[0], 'offline')

    def test_old_failed_probe_does_not_overwrite_new_success_and_last_seen_persists(self):
        self.store.presence_result('lab', True, 20, 'rescue')
        self.store.presence_result('lab', False, 10)
        self.assertEqual(self.store.presence_record('lab')['transport'], 'rescue')
        self.store.presence_result('lab', False, 30)
        restarted = b.Store(self.store.path)
        self.assertEqual(restarted.presence_record('lab')['last_seen'], 20)
        self.assertEqual(restarted.presence_record('lab')['reachable'], 0)

    def test_background_updates_without_alert_subscription_and_uses_readonly_status(self):
        self.bot.monitor_check('lab')
        self.assertEqual(self.bridge.calls, ['xtlsbot-v1 status'])
        self.assertEqual(self.store.presence_record('lab')['reachable'], 1)
        self.assertEqual(self.store.pending_monitor_events(), [])
        self.bot.monitor_check('lab')
        self.assertEqual(len(self.bridge.calls), 1)
        self.bridge.call = lambda *args, **kwargs: (_ for _ in ()).throw(b.TransportError('unreachable'))
        with patch.object(b.time, 'time', return_value=time.time() + 61):
            self.bot.monitor_check('lab')
        self.assertEqual(self.store.presence_record('lab')['reachable'], 0)
        self.assertEqual(self.store.pending_monitor_events(), [])

    def test_background_skips_busy_router_and_menu_does_not_block_on_ssh(self):
        self.bot.locks['lab'].acquire()
        try:
            self.bot.monitor_check('lab')
            self.bot.menu(UID)
            self.assertEqual(self.bridge.calls, [])
        finally:
            self.bot.locks['lab'].release()

    def test_offline_card_is_honest_and_has_retry_without_mutations(self):
        self.store.presence_result('lab', True, time.time() - 60, 'netbird')
        def call(*args, **kwargs): raise b.TransportError('unreachable')
        self.bridge.call = call
        self.bot.status(UID, 'lab')
        self.assertIn('🔴 Нет связи', self.last()['text'])
        self.assertIn('нет свежих данных', self.last()['text'])
        self.assertIn('Последний успешный ответ:', self.last()['text'])
        self.assertNotIn('Прокси: работает', self.last()['text'])

    def test_rich_blocks_have_inline_callbacks_and_literal_untrusted_names(self):
        self.config['rich_messages'] = True
        self.store.rename_router(UID, 'lab', '<b>TEST & </b>')
        self.bot.status(UID, 'lab')
        p = self.last('sendRichMessage')
        self.assertNotIn('reply_markup', p)
        blocks = p['rich_message']['blocks']
        self.assertEqual(blocks[0]['text'], '<b>TEST & </b>')
        self.assertTrue(any(v['type'] == 'blockquote' for v in blocks))
        self.assertTrue(any(v['type'] == 'details' for v in blocks))
        buttons = [btn for v in blocks if v['type'] == 'buttons' for btn in v['buttons']]
        status = next(btn for btn in buttons if btn['text'] == '🔄 Статус')
        self.assertEqual(self.store.take_button(status['callback_data'], UID)['action'], 'status')
        self.assertFalse(any('url' in btn for btn in buttons))  # admin has no support link
        self.assertTrue(p['rich_message']['skip_entity_detection'])

    def test_support_visible_only_for_clients_in_all_views(self):
        self.store.change_access(UID, 123, 'lab', True)
        for uid in (UID, 123):
            for action in (lambda: self.bot.menu(uid), lambda: self.bot.status(uid, 'lab'), lambda: self.bot.help(uid)):
                action()
                buttons = self.last()['reply_markup']['inline_keyboard']
                self.assertEqual(any(v.get('url') == b.SUPPORT_URL for row in buttons for v in row), uid != UID)

    def test_explicit_api_rejection_falls_back_to_same_tokens_but_timeout_does_not(self):
        self.config['rich_messages'] = True
        original = self.tg.call
        for code in (400, 404, None, 429, 500):
            self.tg.calls.clear()
            def call(method, **kwargs):
                if method == 'sendRichMessage':
                    original(method, **kwargs)
                    raise b.SafeError('safe failure', code)
                return original(method, **kwargs)
            self.tg.call = call
            if code in (400, 404):
                self.bot.menu(UID)
                rich_tokens = [btn['callback_data'] for block in self.last('sendRichMessage')['rich_message']['blocks'] if block['type'] == 'buttons' for btn in block['buttons'] if 'callback_data' in btn]
                plain_tokens = [btn['callback_data'] for row in self.last()['reply_markup']['inline_keyboard'] for btn in row if 'callback_data' in btn]
                self.assertEqual(rich_tokens, plain_tokens)
            else:
                with self.assertRaises(b.SafeError): self.bot.menu(UID)
                self.assertFalse(any(m == 'sendMessage' for m, _ in self.tg.calls))
        self.tg.call = original

    def test_config_enables_rich_by_default_without_rewriting_file(self):
        from pathlib import Path
        path = Path(self.tmp.name) / 'config.json'
        config = dict(self.config, bot_username='xtlsproroutbot', database='/tmp/test.db')
        source = json.dumps(config)
        path.write_text(source)
        self.assertTrue(b.load_config(path)['rich_messages'])
        self.assertEqual(path.read_text(), source)
        config['rich_messages'] = False
        path.write_text(json.dumps(config))
        self.assertFalse(b.load_config(path)['rich_messages'])

    def test_status_alive_even_if_location_read_fails(self):
        original = self.bridge.call
        def call(router, command):
            if command.endswith('locations'): raise b.SafeError('safe')
            return original(router, command)
        self.bridge.call = call
        self.bot.status(UID, 'lab')
        self.assertEqual(self.store.presence_record('lab')['reachable'], 1)
        self.assertIn('🟢 В сети', self.last()['text'])
