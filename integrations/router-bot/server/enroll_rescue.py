#!/usr/bin/python3
"""Enroll a local reverse listener; existing router host pin must match."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
from bot import load_config, SafeError

CONFIG = Path('/etc/xtls-router-bot/config.json')
UNIT = 'xtls-router-bot'


def enrolled(config, known, rid, port, host_key):
    if rid not in config['routers'] or type(port) is not int or not 1024 <= port <= 65535:
        raise SafeError('Некорректный роутер или порт резерва.')
    parts = host_key.split()
    if len(parts) != 2 or parts[0] != 'ssh-ed25519':
        raise SafeError('Ожидался публичный ключ Ed25519 без комментария.')
    try:
        raw = base64.b64decode(parts[1], validate=True)
        if len(raw) != 51 or raw[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
            raise ValueError()
    except ValueError:
        raise SafeError('Некорректный публичный ключ.') from None
    router = config['routers'][rid]
    primary = router['host'] if router['port'] == 22 else '[' + router['host'] + ']:' + str(router['port'])
    target = '[127.0.0.1]:' + str(port)
    rows = [line.split() for line in known.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not any(len(row) >= 3 and row[0] == primary and row[1:3] == parts for row in rows):
        raise SafeError('Ключ резерва не совпадает с закреплённым ключом основного адреса роутера.')
    for row in rows:
        if row and target in row[0].split(',') and row[:3] != [target, *parts]:
            raise SafeError('Для аварийного порта уже закреплён другой ключ.')
    for other_id, other in config['routers'].items():
        if other_id != rid and other.get('rescue', {}).get('port') == port:
            raise SafeError('Порт уже закреплён за другим роутером.')
    router['rescue'] = {'host': '127.0.0.1', 'port': port}
    entry = target + ' ' + host_key
    if entry not in known.splitlines():
        known = known.rstrip('\n') + '\n' + entry + '\n'
    return config, known


def replace(path, content):
    info = path.stat()
    fd, name = tempfile.mkstemp(prefix='.rescue-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.chmod(name, info.st_mode & 0o777)
        os.chown(name, info.st_uid, info.st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--host-key', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SafeError('Запусти настройку от root на VPS бота.')
    os.umask(0o077)
    config = load_config(CONFIG)
    known = Path(config['known_hosts'])
    if CONFIG.is_symlink() or known.is_symlink():
        raise SafeError('Ожидались обычные файлы конфигурации и ключей.')
    new_config, new_known = enrolled(config, known.read_text(), args.router, args.port, args.host_key)
    # Validate the complete candidate, including duplicate listener checks.
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / 'config.json'
        candidate.write_text(json.dumps(new_config))
        load_config(candidate)
    command = lambda *parts: subprocess.run(['systemctl', *parts], check=True)
    with sqlite3.connect('file:' + config['database'] + '?mode=ro', uri=True) as db:
        if db.execute("SELECT count(*) FROM operations WHERE state='running'").fetchone()[0]:
            raise SafeError('Выполняется операция роутера. Дождись результата.')
    command('is-active', '--quiet', UNIT)
    backup = Path(tempfile.mkdtemp(prefix='/root/xtls-before-rescue-enrollment-'))
    shutil.copy2(CONFIG, backup / 'config.json')
    shutil.copy2(known, backup / 'known_hosts')
    print('Резервная копия:', backup, flush=True)
    command('stop', UNIT)
    try:
        replace(known, new_known)
        replace(CONFIG, json.dumps(new_config, ensure_ascii=False, indent=2) + '\n')
        command('start', UNIT)
        time.sleep(3)
        command('is-active', '--quiet', UNIT)
    except Exception:
        command('stop', UNIT)
        replace(CONFIG, (backup / 'config.json').read_text())
        replace(known, (backup / 'known_hosts').read_text())
        command('start', UNIT)
        raise
    print('Резервный канал настроен. Проверь карточку LAB и переход при отказе NetBird.')


if __name__ == '__main__':
    try:
        main()
    except SafeError as error:
        print('Остановка:', error)
        raise SystemExit(1)
    except Exception:
        print('Настройка не завершена. Проверь службу; секреты не выводятся.')
        raise SystemExit(1)
