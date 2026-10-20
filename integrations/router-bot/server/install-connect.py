#!/usr/bin/python3
"""Install only operator-side helpers; preserve the running bot and identities."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

APP=Path('/opt/xtls-router-bot')
ALIAS=Path('/usr/local/sbin/xtls-router-add')
CONFIG=Path('/etc/xtls-router-bot/config.json')
TOKEN=Path('/etc/xtls-router-bot/telegram_token')
LOCK=Path('/run/xtls-router-fleet.lock')
FILES={'fleet.py':0o644,'connect.py':0o644,'backup.py':0o644,'xtls-router-add':0o755}


def atomic(path,body,mode):
    if path.is_symlink():raise RuntimeError('Символьная ссылка вместо файла — остановка.')
    fd,name=tempfile.mkstemp(prefix='.connect-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(body)
        os.chmod(name,mode);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def install(source):
    if os.geteuid()!=0:raise RuntimeError('Запусти от root на существующем VPS бота.')
    os.umask(0o077)
    config=json.loads(CONFIG.read_text())
    preserved=[CONFIG,APP/'bot.py',TOKEN,Path(config['ssh_key']),Path(config['known_hosts'])]
    before={p:hashlib.sha256(p.read_bytes()).digest() for p in preserved}
    for name in FILES:
        path=source/name
        if path.is_symlink() or not path.is_file():raise RuntimeError('Отсутствует исходный файл '+name)
        if name.endswith('.py'):compile(path.read_text(),str(path),'exec')
    # Refuse overlapping registrations, but do not restart the daemon.
    import fcntl
    with open(LOCK,'w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        backup=Path(tempfile.mkdtemp(prefix='/root/xtls-before-easy-enroll-'))
        targets={name:ALIAS if name=='xtls-router-add' else APP/name for name in FILES}
        previous={}
        for name,target in targets.items():
            if target.is_symlink():raise RuntimeError('Небезопасная ссылка: '+str(target))
            previous[name]=(target.read_bytes(),target.stat().st_mode&0o777) if target.exists() else None
            if target.exists():shutil.copy2(target,backup/name)
        shutil.copy2(CONFIG,backup/'config.json')
        ALIAS.parent.mkdir(parents=True,exist_ok=True)
        try:
            for name,target in targets.items():atomic(target,(source/name).read_bytes(),FILES[name])
            if any(hashlib.sha256(p.read_bytes()).digest()!=old for p,old in before.items()):raise RuntimeError('Контроль сохранения настроек не пройден.')
        except Exception:
            for name,target in targets.items():
                if previous[name]:atomic(target,*previous[name])
                else:target.unlink(missing_ok=True)
            raise
    print('Мастер установлен: xtls-router-add')
    print('Резервная копия:',backup)
    print('Бот, токен, конфигурация, SSH-ключ и known_hosts сохранены; перезапуск не выполнялся.')


if __name__=='__main__':
    try:install(Path(__file__).resolve().parent)
    except Exception as error:
        print('Установка не завершена:',error);raise SystemExit(1)
