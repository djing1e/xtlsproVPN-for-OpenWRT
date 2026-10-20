import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import types
import os

spec = importlib.util.spec_from_file_location('backup', Path(__file__).resolve().parents[1] / 'server/backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
import test_telegram as pilot


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'source'
        self.root.mkdir()
        self.stage = Path(self.tmp.name)
        backup.install(self.root, activate=False)
        for name in backup.FILES:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            if not file.exists():
                file.write_text('test-secret-' + file.name)
        cfg = {'database': '/' + backup.STATE + 'bot.sqlite3',
               'ssh_key': '/' + backup.STATE + '.ssh/id_ed25519',
               'known_hosts': '/' + backup.STATE + '.ssh/known_hosts'}
        (self.root / backup.CONF / 'config.json').write_text(json.dumps(cfg))
        db = self.root / backup.STATE / 'bot.sqlite3'
        db.unlink()
        self.store = pilot.b.Store(db)
        self.store.change_access(1, 123, 'lab', True)
        self.store.router_code('lab')
        self.store.user_info(123, 'Client')

    def tearDown(self):
        self.tmp.cleanup()

    def test_encrypted_roundtrip_preserves_identity_ids_and_grants(self):
        archive = backup.create(self.root, self.stage)
        output = self.stage / 'restored'
        backup.unpack(archive, backup.key_path(self.root), output, self.stage)
        for name in backup.FILES:
            if name != backup.STATE + 'bot.sqlite3':
                self.assertEqual((self.root / name).read_bytes(), (output / name).read_bytes())
        restored = pilot.b.Store(output / backup.STATE / 'bot.sqlite3')
        self.assertEqual(restored.clients('lab'), [123])
        self.assertEqual(restored.router_code('lab'), 'R-000001')
        self.assertEqual(restored.user_info(123)[0], 'U-000001')
        self.assertFalse((output / backup.CONF / 'backup.key').exists())
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_optional_fleet_registry_tool_survives_encrypted_restore(self):
        name=backup.APP+'fleet.py'
        (self.root/name).write_text('public fleet tool')
        archive=backup.create(self.root,self.stage)
        output=self.stage/'fleet-restored'
        backup.unpack(archive,backup.key_path(self.root),output,self.stage)
        self.assertEqual((output/name).read_text(),'public fleet tool')
        self.assertEqual((output/name).stat().st_mode & 0o777,0o644)

    def test_optional_wizard_and_alias_survive_backup_with_executable_mode(self):
        names={backup.APP+'fleet.py':'fleet',backup.APP+'connect.py':'connect','usr/local/sbin/xtls-router-add':'#!/bin/sh\n'}
        for name,body in names.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
        archive=backup.create(self.root,self.stage)
        output=self.stage/'wizard-restored'
        backup.unpack(archive,backup.key_path(self.root),output,self.stage)
        for name,body in names.items():self.assertEqual((output/name).read_text(),body)
        self.assertEqual((output/'usr/local/sbin/xtls-router-add').stat().st_mode&0o777,0o755)

    def test_operator_helpers_and_units_roundtrip_and_restore_layout(self):
        for name in backup.OPERATOR_FILES:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('operator-'+Path(name).name)
        archive=backup.create(self.root,self.stage)
        recovered=self.stage/'operator-recovered';backup.unpack(archive,backup.key_path(self.root),recovered,self.stage)
        for name in backup.OPERATOR_FILES:self.assertEqual((recovered/name).read_bytes(),(self.root/name).read_bytes())
        destination=self.stage/'operator-vps';destination.mkdir()
        account=types.SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
        with patch.object(backup.pwd,'getpwnam',return_value=account),patch.object(backup.os,'chown'):
            backup.apply_restore(recovered,backup.key_path(self.root),destination,activate=False)
        self.assertEqual((destination/backup.STATE/'operator-inbox').stat().st_mode&0o777,0o700)
        self.assertEqual((destination/'var/lib/xtls-router-operator').stat().st_mode&0o777,0o755)
        self.assertFalse((destination/backup.STATE/'operator-inbox/request.json').exists())

    def test_apply_into_new_vps_tree_preserves_ids_and_refuses_overwrite(self):
        archive = backup.create(self.root, self.stage)
        recovered = self.stage / 'recovered'
        backup.unpack(archive, backup.key_path(self.root), recovered, self.stage)
        new_vps = self.stage / 'new-vps'
        new_vps.mkdir()
        account = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with patch.object(backup.pwd, 'getpwnam', return_value=account):
            backup.apply_restore(recovered, backup.key_path(self.root), new_vps, activate=False)
        self.assertEqual((new_vps / backup.CONF / 'telegram_token').read_bytes(),
                         (self.root / backup.CONF / 'telegram_token').read_bytes())
        restored = pilot.b.Store(new_vps / backup.STATE / 'bot.sqlite3')
        self.assertEqual(restored.clients('lab'), [123])
        self.assertEqual(restored.router_code('lab'), 'R-000001')
        self.assertEqual(backup.key_path(new_vps).read_bytes(), backup.key_path(self.root).read_bytes())
        with self.assertRaises(backup.BackupError):
            backup.apply_restore(recovered, backup.key_path(self.root), new_vps, activate=False)

    def test_fresh_restore_does_not_activate_polling_uploads_or_operator_jobs(self):
        recovered = self.stage/'no-auto-start-source'
        for name in backup.FILES:
            dest = recovered/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((self.root/name).read_bytes())
        destination = self.stage/'no-auto-start-vps'; destination.mkdir()
        account = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with patch.object(backup.pwd, 'getpwnam', return_value=account), patch.object(backup.subprocess, 'run') as run:
            backup.apply_restore(recovered, backup.key_path(self.root), destination, activate=True)
        self.assertEqual([call.args[0] for call in run.call_args_list], [['systemctl', 'daemon-reload']])

    def test_restore_under_private_umask_leaves_application_traversable(self):
        recovered = self.stage / 'plain-source'
        for name in backup.FILES:
            source = self.root / name
            dest = recovered / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())
        destination = self.stage / 'private-umask-vps'
        destination.mkdir()
        account = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        previous = os.umask(0o077)
        try:
            with patch.object(backup.pwd, 'getpwnam', return_value=account):
                backup.apply_restore(recovered, backup.key_path(self.root), destination, activate=False)
        finally:
            os.umask(previous)
        for name in ('opt', 'opt/xtls-router-bot', 'etc', 'etc/xtls-router-bot', 'var', 'var/lib'):
            self.assertEqual((destination / name).stat().st_mode & 0o777, 0o755, name)
        self.assertEqual((destination / backup.STATE).stat().st_mode & 0o777, 0o750)
        self.assertEqual((destination / backup.STATE / '.ssh').stat().st_mode & 0o777, 0o700)
        for name in (backup.CONF+'telegram_token', backup.CONF+'backup.key', backup.STATE+'.ssh/id_ed25519'):
            self.assertEqual((destination / name).stat().st_mode & 0o777, 0o600, name)

    def test_live_database_copy_drops_to_database_owner(self):
        actual = self.root / backup.STATE / 'bot.sqlite3'
        source = MagicMock()
        source.__str__.return_value = str(actual)
        source.stat.return_value = types.SimpleNamespace(st_uid=os.getuid() + 1, st_gid=os.getgid())
        folder = self.stage / 'db-out'
        folder.mkdir()
        def run(args, **kwargs):
            import shutil
            shutil.copyfile(actual, args[-1])
            return types.SimpleNamespace(returncode=0)
        with patch.object(backup.os, 'chown'), patch.object(backup.subprocess, 'run', side_effect=run) as executed:
            backup.sqlite_snapshot(source, folder / 'copy.sqlite3')
        self.assertTrue((folder / 'copy.sqlite3').is_file())
        drop = executed.call_args.kwargs['preexec_fn']
        with patch.object(backup.os, 'setgroups') as groups, patch.object(backup.os, 'setgid') as gid, patch.object(backup.os, 'setuid') as uid:
            drop()
            groups.assert_called_once_with([])
            gid.assert_called_once_with(os.getgid())
            uid.assert_called_once_with(os.getuid() + 1)

    def test_wrong_key_does_not_create_restore_directory(self):
        archive = backup.create(self.root, self.stage)
        wrong = self.stage / 'wrong.key'
        wrong.write_text('incorrect-key')
        with self.assertRaises(backup.BackupError):
            backup.unpack(archive, wrong, self.stage / 'failed', self.stage)
        self.assertFalse((self.stage / 'failed').exists())

    def test_tampered_ciphertext_never_restores(self):
        archive = backup.create(self.root, self.stage)
        damaged = bytearray(archive.read_bytes())
        damaged[-5] ^= 1
        archive.write_bytes(damaged)
        with self.assertRaises(backup.BackupError):
            backup.unpack(archive, backup.key_path(self.root), self.stage / 'damaged', self.stage)
        self.assertFalse((self.stage / 'damaged').exists())

    def test_archive_traversal_and_symlink_rejected(self):
        archive = self.stage / 'malicious.tar.gz'
        for evil in ('../../escape', backup.APP + 'bot.py'):
            with tarfile.open(archive, 'w:gz') as tar:
                for i, name in enumerate([*backup.FILES, 'manifest.json']):
                    info = tarfile.TarInfo(evil if i == 0 else name)
                    if i == 0:
                        info.type = tarfile.SYMTYPE
                        info.linkname = '/etc/shadow'
                        tar.addfile(info)
                    else:
                        body = b'{}'
                        info.size = len(body)
                        tar.addfile(info, io.BytesIO(body))
            with self.assertRaises(backup.BackupError):
                backup.read_archive(archive)

    def test_rotation_retains_latest_fourteen_archives_and_delivery_receipt(self):
        out = self.root/'var/backups/xtls-router-bot'
        out.mkdir(parents=True)
        old = []
        for i in range(16):
            file = out/('xtls-bot-20200101T000000Z-' + format(i, '06x') + '.tar.gpg')
            file.write_bytes(b'older-archive')
            old.append(file)
        receipt = out/'.telegram-delivery.json'
        receipt.write_text('{}')
        latest = backup.create(self.root, self.stage)
        self.assertEqual(len(list(out.glob('xtls-bot-*.tar.gpg'))), 14)
        self.assertTrue(latest.is_file())
        self.assertTrue(receipt.is_file())
        self.assertFalse(any(file.exists() for file in old[:3]))
        self.assertTrue(all(file.exists() for file in old[3:]))

    def test_install_preserves_existing_recovery_key(self):
        before = backup.key_path(self.root).read_bytes()
        backup.install(self.root, activate=False)
        self.assertEqual(backup.key_path(self.root).read_bytes(), before)
        self.assertEqual(backup.key_path(self.root).stat().st_mode & 0o777, 0o600)

    def test_nonstandard_paths_refused_not_silently_omitted(self):
        (self.root / backup.CONF / 'config.json').write_text('{}')
        with self.assertRaises(backup.BackupError):
            backup.create(self.root, self.stage)

    def test_symlink_key_refused(self):
        key = backup.key_path(self.root)
        actual = self.stage / 'real.key'
        key.rename(actual)
        key.symlink_to(actual)
        with self.assertRaises(backup.BackupError):
            backup.create(self.root, self.stage)
