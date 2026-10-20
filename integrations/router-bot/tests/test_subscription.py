import time
import unittest
from unittest.mock import patch
import test_telegram as pilot

UID, b = pilot.UID, pilot.b
CLIENT = 123456789


class SubscriptionTests(unittest.TestCase):
    callback = pilot.TelegramTests.callback
    messages = pilot.TelegramTests.messages
    tearDown = pilot.TelegramTests.tearDown

    def setUp(self):
        pilot.TelegramTests.setUp(self)

    def test_card_dates_usage_and_unlimited_without_raw_fields(self):
        data = {'available': True, 'id': '4242', 'updated': 1792480910,
                'expire': 1830254280, 'used': 42.5 * 1024**3, 'unlimited': True,
                'url': 'SECRET-SUBSCRIPTION-URL', 'title': 'SECRET-TITLE', 'announce': 'SECRET'}
        text = self.bot.subscription_text(data)
        self.assertIn('№4242', text)
        self.assertIn('42.5 ГиБ / безлимит', text)
        self.assertIn('МСК', text)
        self.assertNotIn('SECRET', text)

    def test_customer_number_is_display_only_and_scoped_by_grants(self):
        self.store.cache_subscription('lab', {'id': '4242'})
        self.assertFalse(self.bot.visible(CLIENT))
        self.assertNotIn('4242', self.bot.identity(CLIENT))
        self.store.change_access(UID, CLIENT, 'lab', True)
        self.assertIn('Клиент №4242', self.bot.user_label(CLIENT))
        self.assertNotIn('U-000', self.bot.user_label(CLIENT))
        self.store.change_access(UID, CLIENT, 'lab', False)
        self.assertNotIn('4242', self.bot.identity(CLIENT))

    def test_invalid_ids_are_not_cached_or_displayed(self):
        for value in ['https://SECRET', '4242 SECRET', '4242\nSECRET']:
            self.store.cache_subscription('lab', {'id': value})
            self.assertIsNone(self.store.customer_numbers(CLIENT) or None)
            self.assertNotIn('SECRET', self.bot.subscription_text({'available': True, 'id': value}))

    def test_diagnostics_is_readonly_and_reports_cached_probe(self):
        original = self.bridge.call
        def call(router, command):
            if command == 'xtlsbot-v1 diagnostics':
                self.bridge.calls.append(command)
                return {'running': True, 'memory_available': 64 * 1024**2, 'proxy_ok': True,
                        'interface_up': True, 'interception_active': True}
            return original(router, command)
        self.bridge.call = call
        self.bot.diagnostics(UID, 'lab')
        self.assertEqual(self.bridge.calls, ['xtlsbot-v1 diagnostics'])
        self.assertIn('64.0 МиБ', self.messages()[-1])
        self.assertIn('не запускались', self.messages()[-1])

    def test_monitor_waits_three_failures_and_deduplicates_recovery(self):
        self.store.monitor_enable('lab', True)
        for _ in range(2):
            self.store.monitor_result('lab', False)
        self.assertEqual(self.store.pending_monitor_events(), [])
        self.store.monitor_result('lab', False)
        self.store.monitor_result('lab', False)
        self.assertEqual(len(self.store.pending_monitor_events()), 1)
        self.bot.deliver_notifications()
        self.store.monitor_result('lab', True)
        self.bot.deliver_notifications()
        self.assertEqual(sum('восстановлен' in m for m in self.messages()), 1)

    def test_monitor_does_not_count_same_or_stale_https_snapshot_twice(self):
        self.store.monitor_enable('lab', True)
        now = int(time.time())
        for _ in range(5):
            self.store.monitor_result('lab', True, {'health_checked': now, 'proxy_ok': False})
        self.assertEqual(self.store.monitor_status('lab')['proxy_failures'], 1)
        self.assertEqual(self.store.pending_monitor_events(), [])
        for checked in (now+1, now+2):
            self.store.monitor_result('lab', True, {'health_checked': checked, 'proxy_ok': False})
        events = self.store.pending_monitor_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'proxy')

    def test_clients_cannot_enable_monitor_or_receive_monitor_alerts(self):
        self.store.change_access(UID, CLIENT, 'lab', True)
        epoch = self.store.grant_epoch(CLIENT, 'lab')
        token = self.store.button(CLIENT, 'lab', 'monitor_on', grant_epoch=epoch)
        self.bot.handle(self.callback(token, uid=CLIENT))
        self.assertFalse(self.store.monitor_status('lab')['enabled'])
        self.store.monitor_enable('lab', True)
        for _ in range(3):
            self.store.monitor_result('lab', False)
        self.bot.deliver_notifications()
        alerts = [p for m,p in self.tg.calls if 'Нет ответа' in p.get('text', '')]
        self.assertEqual([p['chat_id'] for p in alerts], [UID])
