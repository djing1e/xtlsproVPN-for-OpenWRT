import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('delivery_backup', Path(__file__).resolve().parents[1] / 'server/backup.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
TOKEN = '123456789:' + 'a'*35
ADMIN = 168179916


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'run').mkdir()
        conf = self.root/b.CONF
        conf.mkdir(parents=True)
        (conf/'config.json').write_text(json.dumps({'admin_id': ADMIN}))
        (conf/'telegram_token').write_text(TOKEN)
        (conf/'backup.key').write_text('private-old-key')
        (conf/'backup.key').chmod(0o600)
        self.out = self.root/'var/backups/xtls-router-bot'
        self.out.mkdir(parents=True)
        self.archive = self.out/'xtls-bot-20261020T090000Z-abcdef.tar.gpg'
        self.archive.write_bytes(b'ciphertext-fixture-only')
        self.receipt = self.out/'.telegram-delivery.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_daily_delivery_persists_confirmation_and_does_not_send_twice(self):
        with patch.object(b, 'create', return_value=self.archive) as create, patch.object(b, 'send_archive', return_value=99) as send:
            b.deliver(self.root)
            b.deliver(self.root)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(send.call_count, 1)
        args = send.call_args.args
        self.assertEqual(args[1:3], (TOKEN, ADMIN))
        saved = json.loads(self.receipt.read_text())
        self.assertEqual(saved['state'], 'sent')
        self.assertEqual(saved['message_id'], 99)
        self.assertNotIn(TOKEN, self.receipt.read_text())
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)

    def test_failure_reuses_same_verified_archive_on_next_invocation(self):
        with patch.object(b, 'create', return_value=self.archive) as create, patch.object(b, 'send_archive', side_effect=[b.BackupError('offline'), 100]) as send:
            with self.assertRaises(b.BackupError): b.deliver(self.root)
            self.assertEqual(json.loads(self.receipt.read_text())['state'], 'pending')
            b.deliver(self.root)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args[0], send.call_args_list[1].args[0])

    def test_pending_archive_tampering_is_not_uploaded(self):
        with patch.object(b, 'create', return_value=self.archive), patch.object(b, 'send_archive', side_effect=b.BackupError('offline')):
            with self.assertRaises(b.BackupError): b.deliver(self.root)
        self.archive.write_bytes(b'changed')
        with patch.object(b, 'send_archive') as send:
            with self.assertRaises(b.BackupError): b.deliver(self.root)
            send.assert_not_called()

    def test_bad_admin_and_symlink_receipt_refused(self):
        conf = self.root/b.CONF/'config.json'
        conf.write_text(json.dumps({'admin_id': -10012345}))
        with patch.object(b, 'send_archive') as send:
            with self.assertRaises(b.BackupError): b.deliver(self.root)
            send.assert_not_called()
        conf.write_text(json.dumps({'admin_id': ADMIN}))
        self.receipt.symlink_to(conf)
        with self.assertRaises(b.BackupError): b.deliver(self.root)

    def test_concurrent_delivery_is_refused_before_creating_or_uploading(self):
        lock = self.root/'run/xtls-router-backup-delivery.lock'
        with lock.open('a') as held, patch.object(b, 'create') as create, patch.object(b, 'send_archive') as send:
            b.fcntl.flock(held, b.fcntl.LOCK_EX | b.fcntl.LOCK_NB)
            with self.assertRaises(b.BackupError): b.deliver(self.root)
            create.assert_not_called()
            send.assert_not_called()

    def response(self, payload):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return response

    def test_multipart_contains_only_ciphertext_and_admin_target(self):
        reply = {'ok': True, 'result': {'chat': {'id': ADMIN}, 'message_id': 23, 'document': {'file_id': 'confirmed'}}}
        opener = MagicMock()
        opener.open.return_value = self.response(reply)
        with patch.object(b.urllib.request, 'build_opener', return_value=opener):
            result = b.send_archive(self.archive, TOKEN, ADMIN, 'a'*64, '2026-10-20')
        self.assertEqual(result, 23)
        request = opener.open.call_args.args[0]
        self.assertIn(self.archive.read_bytes(), request.data)
        self.assertIn(str(ADMIN).encode(), request.data)
        self.assertIn(b'name="document"', request.data)
        self.assertNotIn(TOKEN.encode(), request.data)
        self.assertNotIn(b'backup.key', request.data)
        self.assertEqual(request.full_url, 'https://api.telegram.org/bot'+TOKEN+'/sendDocument')

    def test_bad_response_and_transport_errors_do_not_expose_token(self):
        replies = [[], {'ok': False}, {'ok': True, 'result': {'chat': {'id': 321}, 'message_id': 23, 'document': {}}}]
        for reply in replies:
            opener = MagicMock(); opener.open.return_value = self.response(reply)
            with patch.object(b.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(b.BackupError) as error:
                    b.send_archive(self.archive, TOKEN, ADMIN, 'a'*64, '2026-10-20')
                self.assertNotIn(TOKEN, str(error.exception))
        opener.open.side_effect = urllib.error.URLError('https://api.telegram.org/bot'+TOKEN)
        with patch.object(b.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(b.BackupError) as error:
                b.send_archive(self.archive, TOKEN, ADMIN, 'a'*64, '2026-10-20')
            self.assertNotIn(TOKEN, str(error.exception))

    def test_size_limit_and_moscow_noon_schedule(self):
        self.archive.write_bytes(b'')
        with patch.object(b.urllib.request, 'build_opener') as opener:
            with self.assertRaises(b.BackupError): b.send_archive(self.archive, TOKEN, ADMIN, 'a'*64, '2026-10-20')
            opener.assert_not_called()
        self.assertIn('OnCalendar=*-*-* 12:00:00 Europe/Moscow', b.TIMER)
        self.assertIn('RandomizedDelaySec=0', b.TIMER)
        self.assertIn('AccuracySec=1s', b.TIMER)
        self.assertIn('Persistent=true', b.TIMER)
        self.assertIn('backup.py deliver', b.SERVICE)
        self.assertIn('Restart=on-failure', b.SERVICE)

    def test_moscow_date_not_server_local_date_and_previous_day_sends_again(self):
        real_datetime = b.datetime
        fake = MagicMock()
        fake.now.return_value = real_datetime(2026, 10, 21, 0, 5)
        with patch.object(b, 'create', return_value=self.archive), patch.object(b, 'send_archive', return_value=1) as send, patch.object(b, 'datetime', fake):
            b.deliver(self.root)
        self.assertEqual(send.call_args.args[-1], '2026-10-21')
        self.assertEqual(str(fake.now.call_args.args[0]), 'Europe/Moscow')
        fake.now.return_value = real_datetime(2026, 10, 22, 12, 0)
        with patch.object(b, 'create', return_value=self.archive), patch.object(b, 'send_archive', return_value=2) as send, patch.object(b, 'datetime', fake):
            b.deliver(self.root)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[-1], '2026-10-22')

if __name__ == '__main__': unittest.main()
