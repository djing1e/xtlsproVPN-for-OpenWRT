#!/usr/bin/python3
"""Install daily encrypted Telegram delivery without restarting the router bot."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

APP = Path('/opt/xtls-router-bot/backup.py')
CONFIG = Path('/etc/xtls-router-bot/config.json')
UNIT_DIR = Path('/etc/systemd/system')
TIMER = 'xtls-router-bot-backup.timer'
SERVICE = 'xtls-router-bot-backup.service'


def command(*args, check=True):
    return subprocess.run(['systemctl', *args], check=check)


def active(unit):
    return command('is-active', '--quiet', unit, check=False).returncode == 0


def atomic(path, body, mode):
    if path.is_symlink():
        raise RuntimeError('Небезопасная символьная ссылка.')
    fd, temporary = tempfile.mkstemp(prefix='.daily-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def configure_helper():
    spec = importlib.util.spec_from_file_location('installed_backup_delivery', APP)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.install(activate=False)


def install(source):
    if os.geteuid() != 0:
        raise RuntimeError('Запусти на основном VPS бота от root.')
    os.umask(0o077)
    compile(source.read_text(), str(source), 'exec')
    config = json.loads(CONFIG.read_text())
    if type(config.get('admin_id')) is not int or config['admin_id'] <= 0:
        raise RuntimeError('Некорректный Telegram ID администратора.')
    preserved = [CONFIG, CONFIG.with_name('telegram_token'), CONFIG.with_name('backup.key'),
                 Path(config['ssh_key']), Path(config['known_hosts']), APP.with_name('bot.py')]
    for file in [APP, source, *preserved]:
        if file.is_symlink() or not file.is_file():
            raise RuntimeError('Ожидалась существующая установка без символьных ссылок.')
    before = {file: hashlib.sha256(file.read_bytes()).digest() for file in preserved}
    if not active('xtls-router-bot.service'):
        raise RuntimeError('Ожидался основной VPS с работающим ботом. Тестовую копию не активируем.')
    if active(SERVICE):
        raise RuntimeError('Выполняется резервное копирование; повтори после его завершения.')
    subprocess.run(['/usr/bin/python3', str(APP), 'create'], check=True)
    saved = Path(tempfile.mkdtemp(prefix='/root/xtls-before-daily-telegram-'))
    targets = [APP, UNIT_DIR / SERVICE, UNIT_DIR / TIMER]
    previous = {}
    for file in targets:
        if file.is_symlink(): raise RuntimeError('Символьная ссылка вместо служебного файла.')
        previous[file] = (file.read_bytes(), file.stat().st_mode & 0o777) if file.exists() else None
        if file.exists(): shutil.copy2(file, saved / file.name)
    timer_active = active(TIMER)
    timer_enabled = command('is-enabled', '--quiet', TIMER, check=False).returncode == 0
    command('stop', TIMER)
    try:
        if active(SERVICE):
            raise RuntimeError('Резервное копирование началось во время обновления; повтори позже.')
        atomic(APP, source.read_bytes(), 0o644)
        configure_helper()
        if any(hashlib.sha256(file.read_bytes()).digest() != digest for file, digest in before.items()):
            raise RuntimeError('Контроль сохранения настроек не пройден.')
        command('daemon-reload')
        command('reset-failed', SERVICE, check=False)
        command('enable', TIMER)
        command('restart', TIMER)
    except Exception:
        command('stop', TIMER, check=False)
        for file, old in previous.items():
            if old: atomic(file, *old)
            else: file.unlink(missing_ok=True)
        command('daemon-reload')
        command('enable' if timer_enabled else 'disable', TIMER)
        if timer_active: command('start', TIMER)
        raise
    print('Резервная копия служебных файлов:', saved)
    print('Расписание: ежедневно в 12:00 МСК. Ротация на VPS: 14 архивов.')
    print('Получатель: Telegram ID', config['admin_id'])
    result = command('start', SERVICE, check=False)
    if result.returncode:
        print('Расписание установлено. Первая отправка не подтверждена; проверь журнал службы. Повтор — через 5 минут.')
    else:
        print('Проверочная отправка завершена. Открой личный чат с ботом.')


if __name__ == '__main__':
    try:
        install(Path(__file__).resolve().with_name('backup.py'))
    except Exception:
        print('Установка не завершена. Проверь службу и сохранённые файлы; секреты не выводятся.')
        raise SystemExit(1)
