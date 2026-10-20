#!/usr/bin/python3
"""Encrypted, verified, portable bot backup. Key is deliberately outside archive."""
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

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
OPTIONAL_FILES = {APP + 'fleet.py': 0o644, APP + 'connect.py': 0o644,
                  'usr/local/sbin/xtls-router-add': 0o755,
                  APP+'operator_client.py':0o644,APP+'operator_worker.py':0o644,
                  'etc/systemd/system/xtls-router-bot-operator.service':0o644,
                  'etc/systemd/system/xtls-router-bot-operator.path':0o644}
OPERATOR_FILES={APP+'operator_client.py',APP+'operator_worker.py','etc/systemd/system/xtls-router-bot-operator.service','etc/systemd/system/xtls-router-bot-operator.path'}
ALL_FILES = {**FILES, **OPTIONAL_FILES}
SERVICE = '''[Unit]
Description=Encrypted xtlsproVPN bot backup to Telegram
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=1h
StartLimitBurst=6
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/xtls-router-bot/backup.py deliver
Restart=on-failure
RestartSec=5min
TimeoutStartSec=10min
UMask=0077
PrivateTmp=yes
NoNewPrivileges=yes
'''
TIMER = '''[Unit]
Description=Daily encrypted xtlsproVPN bot backup
[Timer]
OnCalendar=*-*-* 12:00:00 Europe/Moscow
AccuracySec=1s
RandomizedDelaySec=0
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
        if not len(FILES) + 1 <= len(members) <= len(ALL_FILES) + 1:
            raise BackupError('Неожиданный состав архива.')
        data = {}
        for member in members:
            if (member.name not in ALL_FILES and member.name != 'manifest.json') or not member.isfile():
                raise BackupError('Недопустимое имя или тип файла в архиве.')
            if member.name in data or member.size > MAX_FILE:
                raise BackupError('Повтор файла или превышен размер.')
            data[member.name] = archive.extractfile(member).read(MAX_FILE + 1)
        if not set(FILES).issubset(data) or 'manifest.json' not in data:
            raise BackupError('Отсутствует обязательный файл архива.')
        manifest = json.loads(data.pop('manifest.json'))
        if manifest.get('format') != 1 or manifest.get('files') != {n: sha(d) for n, d in data.items()}:
            raise BackupError('Контрольные суммы архива не совпали.')
        if OPERATOR_FILES.intersection(data) and not OPERATOR_FILES.issubset(data):
            raise BackupError('Неполный комплект административного обработчика.')
        config = json.loads(data[CONF + 'config.json'])
        expected = {'database': '/' + STATE + 'bot.sqlite3',
                    'ssh_key': '/' + STATE + '.ssh/id_ed25519',
                    'known_hosts': '/' + STATE + '.ssh/known_hosts'}
        if any(config.get(k) != v for k, v in expected.items()):
            raise BackupError('Пути конфигурации не поддерживаются переносом.')
        return data


def key_path(root):
    return root_path(root, CONF + 'backup.key')


def sqlite_snapshot(path, destination):
    owner = path.stat()
    if owner.st_uid == os.geteuid():
        with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as src, sqlite3.connect(str(destination)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise BackupError('База не прошла проверку целостности.')
        return
    # Open a live WAL database as its owner, so root cannot create root-owned
    # -wal/-shm sidecars that would prevent the running bot from writing later.
    with tempfile.TemporaryDirectory(prefix='xtls-db-copy-', dir=destination.parent.parent) as temp:
        temp = Path(temp)
        os.chown(temp, owner.st_uid, owner.st_gid)
        target = temp / 'state.sqlite3'
        def drop_identity():
            os.setgroups([])
            os.setgid(owner.st_gid)
            os.setuid(owner.st_uid)
        code = ("import sqlite3,sys; "
                "a=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); "
                "b=sqlite3.connect(sys.argv[2]); a.backup(b); "
                "assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
                "b.close(); a.close()")
        result = subprocess.run(['/usr/bin/python3', '-c', code, str(path), str(target)],
                                preexec_fn=drop_identity, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=60)
        if result.returncode:
            raise BackupError('Не удалось снять копию базы от имени её владельца.')
        shutil.copyfile(target, destination)


def snapshot(root, destination):
    data = {}
    config = json.loads(root_path(root, CONF + 'config.json').read_text())
    expected = {'database': '/' + STATE + 'bot.sqlite3', 'ssh_key': '/' + STATE + '.ssh/id_ed25519',
                'known_hosts': '/' + STATE + '.ssh/known_hosts'}
    if any(config.get(k) != v for k, v in expected.items()):
        raise BackupError('Нестандартные пути: резервная копия остановлена.')
    for name in ALL_FILES:
        path = root_path(root, name)
        if name in OPTIONAL_FILES and not path.exists():
            continue
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise BackupError('Отсутствует обязательный файл или превышен размер: ' + name)
        if name == STATE + 'bot.sqlite3':
            sqlite_snapshot(path, destination)
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
                info.size, info.mode = len(body), ALL_FILES.get(name, 0o600)
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



def delivery_state(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.telegram-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def send_archive(archive, token, admin, digest, day):
    size = archive.stat().st_size
    if not 0 < size <= 49_000_000:
        raise BackupError('Архив превышает допустимый размер отправки в Telegram.')
    boundary = 'xtls-backup-' + secrets.token_hex(24)
    caption = ('xtlsproVPN · резервная копия · ' + day + ' МСК\n'
               'Архив зашифрован и проверен.\nSHA256: ' + digest +
               '\nКлюч расшифровки хранится отдельно и не отправляется.')
    parts = []
    for name, value in [('chat_id', str(admin)), ('caption', caption)]:
        parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' +
                      name + '"\r\n\r\n' + value + '\r\n').encode())
    parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="document"; filename="' +
                  archive.name + '"\r\nContent-Type: application/octet-stream\r\n\r\n').encode())
    parts.extend([archive.read_bytes(), ('\r\n--' + boundary + '--\r\n').encode()])
    request = urllib.request.Request('https://api.telegram.org/bot' + token + '/sendDocument',
        data=b''.join(parts), headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=90) as response:
            reply = json.loads(response.read(1_000_001))
    except (OSError, ValueError, urllib.error.URLError):
        # Exceptions/URLs may contain the token. Never print the original error.
        raise BackupError('Отправка копии не подтверждена. Архив сохранён; служба повторит попытку.') from None
    result = reply.get('result') if isinstance(reply, dict) else None
    chat = result.get('chat') if isinstance(result, dict) else None
    document = result.get('document') if isinstance(result, dict) else None
    if (not isinstance(reply, dict) or reply.get('ok') is not True or not isinstance(result, dict) or
            not isinstance(chat, dict) or chat.get('id') != admin or
            type(result.get('message_id')) is not int or result['message_id'] <= 0 or
            not isinstance(document, dict) or not isinstance(document.get('file_id'), str)):
        raise BackupError('Telegram не подтвердил доставку архива администратору.')
    return result['message_id']


def deliver(root=Path('/'), stage_base=Path('/run')):
    config = json.loads(root_path(root, CONF + 'config.json').read_text())
    admin = config.get('admin_id')
    token = root_path(root, CONF + 'telegram_token').read_text().strip()
    if type(admin) is not int or not 0 < admin < 2**52 or not re.fullmatch(r'[0-9]{5,16}:[A-Za-z0-9_-]{20,128}', token):
        raise BackupError('Некорректный Telegram ID администратора или токен бота.')
    out = root_path(root, 'var/backups/xtls-router-bot')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out, 0o700)
    receipt = root_path(root, 'var/backups/xtls-router-bot/.telegram-delivery.json')
    lock = root_path(root, 'run/xtls-router-backup-delivery.lock')
    with lock.open('a') as stream:
        os.chmod(lock, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError('Отправка резервной копии уже выполняется.') from None
        day = datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
        state = {}
        if receipt.exists():
            try:
                state = json.loads(receipt.read_text())
                if not isinstance(state, dict): raise ValueError()
            except (OSError, ValueError):
                raise BackupError('Журнал доставки повреждён; требуется проверка администратора.') from None
        current = state.get('day') == day and state.get('admin') == admin and state.get('bot') == sha(token.encode())
        if current and state.get('state') == 'sent':
            print('Сегодняшняя копия уже доставлена администратору.')
            return
        archive = None
        if current and state.get('state') == 'pending':
            name = state.get('archive', '')
            if not isinstance(name, str) or not re.fullmatch(r'xtls-bot-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{6}\.tar\.gpg', name):
                raise BackupError('Некорректный архив в журнале доставки.')
            candidate = root_path(root, 'var/backups/xtls-router-bot/' + name)
            if candidate.is_file():
                if sha(candidate.read_bytes()) != state.get('sha256'):
                    raise BackupError('Контрольная сумма ожидающего отправки архива не совпала.')
                archive = candidate
        if archive is None:
            archive = create(root, stage_base)
            state = {'day': day, 'admin': admin, 'bot': sha(token.encode()), 'state': 'pending',
                     'archive': archive.name, 'sha256': sha(archive.read_bytes())}
            delivery_state(receipt, state)
        message = send_archive(archive, token, admin, state['sha256'], day)
        state.update(state='sent', message_id=message)
        delivery_state(receipt, state)
        print('Зашифрованная копия доставлена администратору:', archive.name)

def operator_layout(root=Path('/'),activate=True):
    unit=root_path(root,'etc/systemd/system/xtls-router-bot-operator.path')
    if not unit.exists():return
    user=pwd.getpwnam('xtlsrouterbot')
    inbox=root_path(root,STATE+'operator-inbox')
    inbox.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(inbox,0o700);os.chown(inbox,user.pw_uid,user.pw_gid)
    results=root_path(root,'var/lib/xtls-router-operator')
    results.mkdir(parents=True,exist_ok=True,mode=0o755)
    os.chmod(results,0o755);os.chown(results,0,0)
    if activate:
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','enable','--now','xtls-router-bot-operator.path'],check=True)


def install(root=Path('/'), activate=True):
    operator_layout(root,activate)
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
            os.chmod(file, ALL_FILES[name])
        with sqlite3.connect(str(destination / STATE / 'bot.sqlite3')) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise BackupError('Восстановленная база не прошла проверку.')
        return destination


def restore_parents(root, parent):
    # mkdir(mode=0755) is reduced to 0700 by the root-only restore umask.
    # Set modes on newly created directories explicitly; never chmod existing
    # system directories or follow symlinks.
    missing = []
    while parent != root and not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o755)
        os.chmod(directory, 0o755)


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
    for name in ALL_FILES:
        if name in OPTIONAL_FILES and not (directory / name).exists():
            continue
        dest = root_path(root, name)
        restore_parents(root, dest.parent)
        shutil.copyfile(directory / name, dest)
        os.chmod(dest, ALL_FILES[name])
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
    # Restored copies must not start polling, operator jobs or scheduled uploads.
    install(root, activate=False)
    if activate:
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
    # Deliberately do not start polling until the previous bot is stopped and
    # this VPS has joined NetBird. NetBird identity is not cloned in this backup.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'create', 'deliver', 'restore'])
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
        print('Ежедневная отправка администратору в 12:00 МСК включена; на VPS сохраняются последние 14 архивов.')
        print('Ключ восстановления:', key_path(Path('/')))
        print('Скачай ключ отдельно от архива и сохрани вне VPS. Без него восстановление невозможно.')
    elif args.action == 'deliver':
        deliver()
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
