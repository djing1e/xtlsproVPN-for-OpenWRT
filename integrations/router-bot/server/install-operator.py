#!/usr/bin/python3
"""Upgrade admin UI and install a fixed-action root oneshot, preserving credentials."""
import hashlib
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import backup
import upgrade

APP=Path('/opt/xtls-router-bot')
UNITS=Path('/etc/systemd/system')
HELPERS=('fleet.py','connect.py','backup.py','operator_client.py','operator_worker.py')
UNITS_NAMES=('xtls-router-bot-operator.service','xtls-router-bot-operator.path')

def atomic(path,data,mode=0o644):
    if path.is_symlink():raise RuntimeError('Unexpected symlink')
    fd,name=tempfile.mkstemp(prefix='.operator-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data)
        os.chmod(name,mode);os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def main():
    if os.geteuid()!=0:raise RuntimeError('Run as root on bot VPS')
    os.umask(0o077)
    source=Path(__file__).resolve().parent
    for name in (*HELPERS,'bot.py','upgrade.py'):
        compile((source/name).read_text(),str(source/name),'exec')
    if subprocess.run(['systemctl','is-active','--quiet','xtls-router-bot-operator.service']).returncode==0:
        raise RuntimeError('Administrative operation is running; retry after completion')
    path_active=subprocess.run(['systemctl','is-active','--quiet','xtls-router-bot-operator.path']).returncode==0
    print('Проверенная копия до обновления:',backup.create(),flush=True)
    folder=Path(tempfile.mkdtemp(prefix='/root/xtls-before-bot-operator-'))
    targets={**{APP/name:source/name for name in HELPERS},**{UNITS/name:source/name for name in UNITS_NAMES}}
    previous={}
    for target in (*targets,APP/'bot.py'):
        if target.is_symlink():raise RuntimeError('Unexpected symlink')
        previous[target]=target.read_bytes() if target.exists() else None
        if target.exists():shutil.copy2(target,folder/target.name)
    try:
        if path_active:
            subprocess.run(['systemctl','stop','xtls-router-bot-operator.path'],check=True)
            if subprocess.run(['systemctl','is-active','--quiet','xtls-router-bot-operator.service']).returncode==0:
                raise RuntimeError('Administrative operation started; retry later')
        for target,path in targets.items():atomic(target,path.read_bytes())
        upgrade.main()
        backup.operator_layout()
    except Exception:
        subprocess.run(['systemctl','stop','xtls-router-bot'],check=False)
        for target,data in previous.items():
            if data is None:target.unlink(missing_ok=True)
            else:atomic(target,data)
        subprocess.run(['systemctl','daemon-reload'],check=False)
        subprocess.run(['systemctl','start','xtls-router-bot'],check=False)
        if path_active:subprocess.run(['systemctl','start','xtls-router-bot-operator.path'],check=False)
        raise
    print('Админ-меню установлено. Служебные файлы сохранены:',folder)
    print('Проверенная зашифрованная копия:',backup.create())

if __name__=='__main__':
    try:
        with open('/run/xtls-router-fleet.lock','w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            main()
    except Exception:
        print('Установка не завершена. Проверьте службу; секреты не выводятся.')
        raise SystemExit(1)
