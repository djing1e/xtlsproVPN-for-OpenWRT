import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_backup as fixtures

b = fixtures.backup
PASSWORD = 'five unrelated test words for recovery 2026'
TOKEN = '123456789:'+'a'*35


class BackupPasswordTests(unittest.TestCase):
    def setUp(self):
        fixtures.BackupTests.setUp(self)
        (self.root/'run').mkdir()
        config = self.root/b.CONF/'config.json'
        value = json.loads(config.read_text()); value['admin_id'] = 168179916
        config.write_text(json.dumps(value))
        (self.root/b.CONF/'telegram_token').write_text(TOKEN)
        self.key = b.key_path(self.root)
        self.old = self.key.read_bytes()

    tearDown = fixtures.BackupTests.tearDown

    def test_new_password_roundtrip_and_pending_delivery_uses_verified_archive(self):
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            archive, previous = b.change_password(PASSWORD, self.root, self.stage)
        self.assertNotIn(PASSWORD, console.getvalue())
        self.assertEqual(self.key.read_bytes(), (PASSWORD+'\n').encode())
        self.assertEqual(previous.read_bytes(), self.old)
        self.assertEqual(previous.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
        recovered = self.stage/'password-recovered'
        b.unpack(archive, self.key, recovered, self.stage)
        self.assertFalse((recovered/b.CONF/'backup.key').exists())
        with self.assertRaises(b.BackupError):
            b.unpack(archive, previous, self.stage/'old-key-cannot-open-new', self.stage)
        with patch.object(b, 'send_archive', return_value=7) as send, patch.object(b, 'create') as create:
            b.deliver(self.root, self.stage)
            create.assert_not_called()
            self.assertEqual(send.call_args.args[0], archive)

    def test_old_archive_still_opens_with_saved_previous_key(self):
        old_archive = b.create(self.root, self.stage)
        archive, previous = b.change_password(PASSWORD, self.root, self.stage)
        b.unpack(old_archive, previous, self.stage/'old-recovered', self.stage)
        with self.assertRaises(b.BackupError):
            b.unpack(old_archive, self.key, self.stage/'new-key-cannot-open-old', self.stage)

    def test_failed_candidate_verification_does_not_replace_live_key(self):
        with patch.object(b, '_create', side_effect=b.BackupError('verification failed')):
            with self.assertRaises(b.BackupError): b.change_password(PASSWORD, self.root, self.stage)
        self.assertEqual(self.key.read_bytes(), self.old)
        self.assertEqual(list(self.key.parent.glob('backup.key.previous-*')), [])

    def test_receipt_failure_rolls_back_key_and_previous_receipt(self):
        out = b.archive_directory(self.root)
        receipt = out/'.telegram-delivery.json'; receipt.write_text('{"state":"old"}')
        with patch.object(b, 'delivery_state', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): b.change_password(PASSWORD, self.root, self.stage)
        self.assertEqual(self.key.read_bytes(), self.old)
        self.assertEqual(receipt.read_text(), '{"state":"old"}')

    def test_invalid_passwords_never_change_key(self):
        for password in ['', 'short', 'a'*20+'\nsecond line', 'a'*20+'\x00', 'a'*1025]:
            with self.assertRaises(b.BackupError): b.change_password(password, self.root, self.stage)
        self.assertEqual(self.key.read_bytes(), self.old)

    def test_noninteractive_or_mismatching_prompt_refused(self):
        with patch.object(b.sys.stdin, 'isatty', return_value=False), patch.object(b.getpass, 'getpass') as prompt:
            with self.assertRaises(b.BackupError): b.prompt_password(new=True)
            prompt.assert_not_called()
        with patch.object(b.sys.stdin, 'isatty', return_value=True), patch.object(b.getpass, 'getpass', side_effect=[PASSWORD, 'different']):
            with self.assertRaises(b.BackupError): b.prompt_password(new=True)
        self.assertEqual(self.key.read_bytes(), self.old)

    def test_password_change_refuses_active_delivery(self):
        lock = self.root/'run/xtls-router-backup-delivery.lock'
        with lock.open('a') as held, patch.object(b, '_create') as create:
            b.fcntl.flock(held, b.fcntl.LOCK_EX | b.fcntl.LOCK_NB)
            with self.assertRaises(b.BackupError): b.change_password(PASSWORD, self.root, self.stage)
            create.assert_not_called()
        self.assertEqual(self.key.read_bytes(), self.old)

    def test_cli_restore_with_typed_password_needs_no_original_key_file(self):
        archive, previous = b.change_password(PASSWORD, self.root, self.stage)
        self.key.unlink(); previous.unlink()
        output = self.stage/'typed-restore'
        argv = ['backup.py', 'restore', str(archive), '--ask-passphrase', '--output', str(output)]
        with patch.object(b.sys, 'argv', argv), patch.object(b.os, 'geteuid', return_value=0), patch.object(b.sys.stdin, 'isatty', return_value=True), patch.object(b.getpass, 'getpass', return_value=PASSWORD):
            b.main()
        self.assertTrue((output/b.STATE/'bot.sqlite3').is_file())
        self.assertFalse((output/b.CONF/'backup.key').exists())

if __name__ == '__main__': unittest.main()
