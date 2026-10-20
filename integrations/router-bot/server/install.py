#!/usr/bin/python3
"""Run locally on the bot VPS as root; token never enters shell arguments."""
import getpass
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time

from bot import Telegram, SafeError

BASE = Path('/opt/xtls-router-bot')
CONF = Path('/etc/xtls-router-bot')
STATE = Path('/var/lib/xtls-router-bot')
HOST = '100.124.249.61'
HOST_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGvOWJsdfLieCYoFuZ9MB2UgQHh6s+0yfZm+VVdLR5Ox'


def write_atomic(path, data, mode=0o600, owner=None):
    if path.is_symlink():
        raise SafeError('Symlink destination refused')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.new-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
        os.chmod(name, mode)
        if owner:
            os.chown(name, *owner)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise SafeError('Run as root in an interactive terminal')
    os.umask(0o077)
    here = Path(__file__).resolve().parent
    for file in ('bot.py', 'xtls-router-bot.service'):
        if not (here / file).is_file():
            raise SafeError('Incomplete download')
    for command in ('ssh', 'ssh-keygen', 'systemctl', 'runuser'):
        if not shutil.which(command):
            raise SafeError('Required command missing: ' + command)
    user = pwd.getpwnam('xtlsrouterbot')
    owner = (user.pw_uid, user.pw_gid)
    key = STATE / '.ssh/id_ed25519'
    known = STATE / '.ssh/known_hosts'
    for directory in (BASE, CONF, STATE, STATE / '.ssh'):
        if directory.is_symlink():
            raise SafeError('Symlink directory refused')
    if not key.is_file() or key.is_symlink():
        raise SafeError('Existing bot SSH key missing; no key is generated or replaced')
    identity = subprocess.run(['runuser', '-u', 'xtlsrouterbot', '--', 'ssh-keygen', '-y', '-f', str(key)],
                              capture_output=True, text=True, timeout=10)
    expected = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMU9f6nqzVlV1VTmO9qVc7Tn2nZSse6IZCglzH6oW5RX'
    if identity.returncode or ' '.join(identity.stdout.split()[:2]) != expected:
        raise SafeError('SSH identity differs from the key tested on LAB')
    lookup = subprocess.run(['ssh-keygen', '-F', HOST, '-f', str(known)],
                            capture_output=True, text=True, timeout=10)
    entries = [line.split() for line in lookup.stdout.splitlines() if line and not line.startswith('#')]
    if not entries or any(' '.join(line[1:3]) != HOST_KEY for line in entries):
        raise SafeError('Pinned LAB host key missing or differs from the verified key')

    print('Токен вводится скрыто и не попадёт в историю команд.', flush=True)
    token = getpass.getpass('Вставь токен @xtlsproroutbot: ').strip()
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
        raise SafeError('Некорректный формат токена')
    telegram = Telegram(token)
    if telegram.call('getMe').get('username', '').lower() != 'xtlsproroutbot':
        raise SafeError('Токен принадлежит другому боту')
    if telegram.call('getWebhookInfo').get('url'):
        raise SafeError('У бота уже настроен webhook; установка остановлена без его изменения')

    backup = Path(tempfile.mkdtemp(prefix='/root/xtls-before-telegram-'))
    os.chmod(backup, 0o700)
    for source, label in ((BASE, 'app'), (CONF, 'config')):
        if source.exists():
            shutil.copytree(source, backup / label, symlinks=True)
    unit = Path('/etc/systemd/system/xtls-router-bot.service')
    if unit.exists():
        shutil.copy2(unit, backup / unit.name)
    BASE.mkdir(mode=0o755, exist_ok=True)
    CONF.mkdir(mode=0o755, exist_ok=True)
    os.chmod(BASE, 0o755)
    os.chmod(CONF, 0o755)
    config = {
        'admin_id': 168179916, 'bot_username': 'xtlsproroutbot',
        'ssh_key': str(key), 'known_hosts': str(known),
        'database': str(STATE / 'bot.sqlite3'),
        'routers': {'lab': {'name': 'LAB · Cudy WR3000U', 'host': HOST, 'port': 22}},
    }
    if (CONF / 'config.json').exists():
        from bot import load_config
        existing = load_config(CONF / 'config.json')
        if existing != config:
            raise SafeError('Existing config differs; retained unchanged for review')
    # Files deployed as root; service user can read, but not modify application/config.
    write_atomic(BASE / 'bot.py', (here / 'bot.py').read_text(), 0o644)
    write_atomic(CONF / 'config.json', json.dumps(config, ensure_ascii=False, indent=2) + '\n', 0o644)
    write_atomic(CONF / 'telegram_token', token + '\n', 0o600)
    write_atomic(unit, (here / unit.name).read_text(), 0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', 'xtls-router-bot'], check=True)
    subprocess.run(['systemctl', 'restart', 'xtls-router-bot'], check=True)
    time.sleep(3)
    subprocess.run(['systemctl', 'is-active', '--quiet', 'xtls-router-bot'], check=True)
    print('Резервная копия:', backup)
    print('Служба запущена. Открой @xtlsproroutbot и отправь /start.')
    print('Доступ разрешён только Telegram ID 168179916; роутер: LAB.')


if __name__ == '__main__':
    try:
        main()
    except SafeError as error:
        print('Остановка:', error, file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Установка не завершена; проверь файлы, сеть и состояние службы. Токен не выводится.', file=sys.stderr)
        sys.exit(1)
