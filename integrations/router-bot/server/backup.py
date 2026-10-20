#!/usr/bin/python3
"""Encrypted, verified, portable bot backup. Key is deliberately outside archive."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

APP = 'opt/xtls-router-bot/'
CONF = 'etc/xtls-router-bot/'
STATE = 'var/lib/xtls-router-bot/'
FILES = {
    APP + 'bot.py': 0o644,
    APP + 'backup.py': 0o644,
    CONF + 'config.json': 0o644,
    CONF + 'telegram_token': 0o600,
    STATE + '.ssh/id_ed25519': 0o600,
    STATE + '.ssh/known_hosts': 0o600,
    STATE + 'bot.sqlite3': 0o600,
    'etc/systemd/system/xtls-router-bot.service': 0o644,
}
SERVICE = '''[Unit]
Description=Encrypted xtlsproVPN bot backup
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/xtls-router-bot/backup.py create
UMask=0077
PrivateTmp=yes
NoNewPrivileges=yes
'''
TIMER = '''[Unit]
Description=Daily encrypted xtlsproVPN bot backup
[Timer]
OnCalendar=*-*-* 03:15:00
RandomizedDelaySec=15m
Persistent=true
[Install]
WantedBy=timers.target
'''
MAX_FILE = 64 * 1024 * 1024


class BackupError(Exception):
    pass


def root_path(root, name):
    path = root / name
    for parent in [path, *path.parents]:
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise BackupError('Символьные ссылки в путях копии запрещены.')
    return path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def gpg(source, dest, key, home, decrypt=False):
    home.mkdir(mode=0o700)
    args = ['gpg', '--batch', '--yes', '--no-tty', '--homedir', str(home),
            '--pinentry-mode', 'loopback', '--no-symkey-cache',
            '--passphrase-file', str(key), '--output', str(dest)]
    args += ['--decrypt'] if decrypt else ['--cipher-algo', 'AES256', '--s2k-count', '65011712', '--symmetric']
    args.append(str(source))
    result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    if result.returncode:
        raise BackupError('Не удалось расшифровать/зашифровать копию. Проверь ключ и целостность архива.')


def read_archive(path):
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) != len(FILES) + 1:
            raise BackupError('Неожиданный состав архива.')
        data = {}
        for member in members:
            if (member.name not in FILES and member.name != 'manifest.json') or not member.isfile():
                raise BackupError('Недопустимое имя или тип файла в архиве.')
            if member.name in data or member.size > MAX_FILE:
                raise BackupError('Повтор файла или превышен размер.')
            data[member.name] = archive.extractfile(member).read(MAX_FILE + 1)
        manifest = json.loads(data.pop('manifest.json'))
        if manifest.get('format') != 1 or manifest.get('files') != {n: sha(d) for n, d in data.items()}:
            raise BackupError('Контрольные суммы архива не совпали.')
        config = json.loads(data[CONF + 'config.json'])
        expected = {'database': '/' + STATE + 'bot.sqlite3',
                    'ssh_key': '/' + STATE + '.ssh/id_ed25519',
                    'known_hosts': '/' + STATE + '.ssh/known_hosts'}
        if any(config.get(k) != v for k, v in expected.items()):
            raise BackupError('Пути конфигурации не поддерживаются переносом.')
        return data


def key_path(root):
    return root_path(root, CONF + 'backup.key')


def snapshot(root, destination):
    data = {}
    config = json.loads(root_path(root, CONF + 'config.json').read_text())
    expected = {'database': '/' + STATE + 'bot.sqlite3', 'ssh_key': '/' + STATE + '.ssh/id_ed25519',
                'known_hosts': '/' + STATE + '.ssh/known_hosts'}
    if any(config.get(k) != v for k, v in expected.items()):
        raise BackupError('Нестандартные пути: резервная копия остановлена.')
    for name in FILES:
        path = root_path(root, name)
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise BackupError('Отсутствует обязательный файл или превышен размер: ' + name)
        if name == STATE + 'bot.sqlite3':
            with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as src, sqlite3.connect(str(destination)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise BackupError('База не прошла проверку целостности.')
            data[name] = destination.read_bytes()
        else:
            data[name] = path.read_bytes()
    return data


def create(root=Path('/'), stage_base=Path('/run')):
    out = root_path(root, 'var/backups/xtls-router-bot')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out, 0o700)
    key = key_path(root)
    if not key.is_file() or key.stat().st_mode & 0o077:
        raise BackupError('Ключ резервной копии отсутствует или доступен другим пользователям.')
    with tempfile.TemporaryDirectory(prefix='xtls-backup-', dir=stage_base) as temp:
        stage = Path(temp)
        data = snapshot(root, stage / 'state.sqlite3')
        data['manifest.json'] = json.dumps({'format': 1, 'files': {n: sha(d) for n, d in data.items()}}, sort_keys=True).encode()
        plain = stage / 'backup.tar.gz'
        with tarfile.open(plain, 'w:gz') as archive:
            for name, body in data.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(body), FILES.get(name, 0o600)
                archive.addfile(info, io.BytesIO(body))
        encrypted = stage / 'backup.tar.gpg'
        gpg(plain, encrypted, key, stage / 'encrypt')
        # Test decryption and integrity before publishing and rotating any copy.
        checked = stage / 'checked.tar.gz'
        gpg(encrypted, checked, key, stage / 'verify', decrypt=True)
        read_archive(checked)
        filename = 'xtls-bot-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(3) + '.tar.gpg'
        final = out / filename
        fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=out)
        os.close(fd)
        try:
            shutil.copyfile(encrypted, temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, final)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        for old in sorted(out.glob('xtls-bot-*.tar.gpg'), reverse=True)[14:]:
            old.unlink()
        return final


def install(root=Path('/'), activate=True):
    if not shutil.which('gpg'):
        raise BackupError('Установи gnupg перед настройкой копий.')
    root_path(root, CONF).mkdir(parents=True, exist_ok=True, mode=0o755)
    key = key_path(root)
    if not key.exists():
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_hex(32) + '\n')
    elif key.stat().st_mode & 0o077:
        raise BackupError('Ключ должен иметь права 600.')
    app = root_path(root, APP + 'backup.py')
    app.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if app.resolve() != Path(__file__).resolve():
        shutil.copyfile(__file__, app)
    os.chmod(app, 0o644)
    units = root_path(root, 'etc/systemd/system')
    units.mkdir(parents=True, exist_ok=True)
    for name, body in [('xtls-router-bot-backup.service', SERVICE), ('xtls-router-bot-backup.timer', TIMER)]:
        file = root_path(root, 'etc/systemd/system/' + name)
        file.write_text(body)
        os.chmod(file, 0o644)
    if activate:
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', '--now', 'xtls-router-bot-backup.timer'], check=True)


def unpack(archive, key, destination, stage_base=Path('/run')):
    if destination.exists():
        raise BackupError('Каталог восстановления уже существует. Выбери новый пустой путь.')
    with tempfile.TemporaryDirectory(prefix='xtls-restore-', dir=stage_base) as temp:
        stage = Path(temp)
        gpg(archive, stage / 'plain.tar.gz', key, stage / 'gpg', decrypt=True)
        data = read_archive(stage / 'plain.tar.gz')
        destination.mkdir(parents=True, mode=0o700)
        for name, body in data.items():
            file = root_path(destination, name)
            file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            file.write_bytes(body)
            os.chmod(file, FILES[name])
        with sqlite3.connect(str(destination / STATE / 'bot.sqlite3')) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise BackupError('Восстановленная база не прошла проверку.')
        return destination


def apply_restore(directory, key, root=Path('/'), activate=True):
    # Only on a new VPS. Never overwrite an existing live bot installation.
    for name in (APP, CONF, STATE, 'etc/systemd/system/xtls-router-bot.service'):
        if root_path(root, name).exists():
            raise BackupError('Применение разрешено только на новом VPS без установленного бота.')
    try:
        user = pwd.getpwnam('xtlsrouterbot')
    except KeyError:
        if not activate:
            raise BackupError('Для тестового восстановления нужен существующий пользователь.')
        subprocess.run(['useradd', '--system', '--user-group', '--home-dir', '/' + STATE.rstrip('/'),
                        '--shell', '/usr/sbin/nologin', 'xtlsrouterbot'], check=True)
        user = pwd.getpwnam('xtlsrouterbot')
    for name in FILES:
        dest = root_path(root, name)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        shutil.copyfile(directory / name, dest)
        os.chmod(dest, FILES[name])
    state = root_path(root, STATE)
    os.chown(state, user.pw_uid, user.pw_gid)
    os.chmod(state, 0o750)
    ssh = state / '.ssh'
    os.chown(ssh, user.pw_uid, user.pw_gid)
    os.chmod(ssh, 0o700)
    for name in (STATE + 'bot.sqlite3', STATE + '.ssh/id_ed25519', STATE + '.ssh/known_hosts'):
        os.chown(root_path(root, name), user.pw_uid, user.pw_gid)
    shutil.copyfile(key, key_path(root))
    os.chmod(key_path(root), 0o600)
    install(root, activate=activate)
    if activate:
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'xtls-router-bot'], check=True)
    # Deliberately do not start polling until the previous bot is stopped and
    # this VPS has joined NetBird. NetBird identity is not cloned in this backup.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'create', 'restore'])
    parser.add_argument('archive', nargs='?')
    parser.add_argument('--key-file')
    parser.add_argument('--output')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise BackupError('Запусти от root.')
    os.umask(0o077)
    if args.action == 'install':
        install()
        print('Ежедневное копирование включено; сохраняются последние 14 архивов.')
        print('Ключ восстановления:', key_path(Path('/')))
        print('Скачай ключ отдельно от архива и сохрани вне VPS. Без него восстановление невозможно.')
    elif args.action == 'create':
        print('Проверенная зашифрованная копия:', create())
    else:
        if not args.archive or not args.key_file or not args.output:
            raise BackupError('Нужны archive --key-file KEY --output NEW_DIRECTORY.')
        restored = unpack(Path(args.archive).resolve(), Path(args.key_file).resolve(), Path(args.output).absolute())
        if args.apply:
            apply_restore(restored, Path(args.key_file).resolve())
            print('Бот восстановлен и оставлен остановленным. Подключи новый VPS к NetBird, останови старую копию бота и запусти службу.')
        else:
            print('Копия проверена и распакована:', restored)
            print('Система не изменена. Каталог содержит секреты; сохрани права 700.')


if __name__ == '__main__':
    try:
        main()
    except BackupError as error:
        print('Остановка:', error, file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Операция копирования/восстановления не завершена. Проверь аргументы, файлы и права; секреты не выводятся.', file=sys.stderr)
        sys.exit(1)
