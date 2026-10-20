#!/usr/bin/python3
"""Update the bot application without changing its token, config or SSH identity."""
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from bot import Store, load_config, SafeError

UNIT = 'xtls-router-bot'
APP = Path('/opt/xtls-router-bot/bot.py')
CONFIG = Path('/etc/xtls-router-bot/config.json')
TOKEN = Path('/etc/xtls-router-bot/telegram_token')


def command(*args):
    return subprocess.run(['systemctl', *args], check=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def running_operations(database):
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True) as db:
        return db.execute("SELECT count(*) FROM operations WHERE state='running'").fetchone()[0]


def atomic_app(source):
    fd, name = tempfile.mkstemp(prefix='.bot-', dir=APP.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source.read_bytes())
        os.chmod(name, 0o644)
        os.replace(name, APP)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    if os.geteuid() != 0:
        raise SafeError('Запусти обновление от root на VPS бота.')
    os.umask(0o077)
    source = Path(__file__).resolve().with_name('bot.py')
    compile(source.read_text(), str(source), 'exec')
    for file in (APP, CONFIG, TOKEN):
        if not file.is_file() or file.is_symlink():
            raise SafeError('Ожидалась существующая установка без символьных ссылок.')
    config = load_config(CONFIG)
    database = Path(config['database'])
    if not database.is_file() or database.is_symlink():
        raise SafeError('База работающего бота не найдена.')
    preserved = {p: digest(p) for p in (CONFIG, TOKEN, Path(config['ssh_key']), Path(config['known_hosts']))}
    if running_operations(database):
        raise SafeError('Выполняется операция роутера. Дождись результата и повтори обновление.')
    command('is-active', '--quiet', UNIT)
    backup = Path(tempfile.mkdtemp(prefix='/root/xtls-before-client-access-'))
    os.chmod(backup, 0o700)
    shutil.copy2(APP, backup / 'bot.py')
    shutil.copy2(CONFIG, backup / 'config.json')
    command('stop', UNIT)
    replaced = False
    try:
        if running_operations(database):
            raise SafeError('Операция началась во время обновления. Старое приложение сохранено; проверь статус роутера.')
        # SQLite backup, not a raw copy of a live WAL database.
        with sqlite3.connect(str(database)) as src, sqlite3.connect(str(backup / 'bot.sqlite3')) as dest:
            src.backup(dest)
        probe = backup / 'migration-check.sqlite3'
        shutil.copy2(backup / 'bot.sqlite3', probe)
        Store(probe)
        with sqlite3.connect(str(probe)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SafeError('Проверка миграции базы не пройдена.')
        probe.unlink()
        atomic_app(source)
        replaced = True
        command('start', UNIT)
        time.sleep(3)
        command('is-active', '--quiet', UNIT)
        if any(digest(path) != before for path, before in preserved.items()):
            raise SafeError('Контроль сохранения файлов не пройден.')
    except Exception:
        command('stop', UNIT)
        if replaced:
            atomic_app(backup / 'bot.py')
        # Schema additions are compatible with the old application. Never rewind
        # the database: that could discard access changes made after startup.
        command('start', UNIT)
        raise
    print('Обновлено. Резервная копия:', backup)
    print('Токен, конфигурация, SSH-ключ и known_hosts сохранены.')
    print('Открой бота: роутер → «Доступ клиентов» → «Добавить клиента».')


if __name__ == '__main__':
    try:
        main()
    except SafeError as error:
        print('Остановка:', error, file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Обновление не завершено. Проверь состояние службы; секреты не выводятся.', file=sys.stderr)
        sys.exit(1)
