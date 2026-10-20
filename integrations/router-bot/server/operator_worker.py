#!/usr/bin/python3
"""Root oneshot: only encrypted backup or verified fleet enrollment, never shell."""
from contextlib import redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile
import time

import backup
import connect
import fleet
from bot import load_config,SafeError
from operator_client import valid_name

INBOX=Path('/var/lib/xtls-router-bot/operator-inbox')
RESULTS=Path('/var/lib/xtls-router-operator')
CONFIG=Path('/etc/xtls-router-bot/config.json')

def validate(value,config):
    if not isinstance(value,dict) or set(value)!={'id','action','uid','created','code','name'}:raise ValueError('request fields')
    if not isinstance(value['id'],str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value['id']):raise ValueError('id')
    if type(value['uid']) is not int or value['uid']!=config['admin_id']:raise ValueError('admin required')
    if type(value['created']) is not int or not -30<=time.time()-value['created']<=600:raise ValueError('expired')
    if value['action']=='backup':
        if value['code']!='' or value['name']!='':raise ValueError('backup arguments')
    elif value['action']=='enroll':
        connect.pairing(value['code'])
        if not valid_name(value['name']):raise ValueError('name')
        if not config.get('fleet_profile'):raise ValueError('profile required')
    else:raise ValueError('action')
    return value

def save(value):
    fd,path=tempfile.mkstemp(prefix='.result-',dir=RESULTS)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False)
        os.chmod(path,0o644);os.replace(path,RESULTS/(value['id']+'.json'))
    finally:Path(path).unlink(missing_ok=True)

def execute(value,config):
    if value['action']=='backup':
        path=backup.create()
        return 'Проверенная зашифрованная копия создана:\n'+str(path)+'\nКлюч восстановления хранится отдельно; сохраните архив и ключ вне VPS.'
    with connect.lock():
        current=load_config(CONFIG)
        if current.get('fleet_profile')!=config.get('fleet_profile'):raise SafeError('Профиль изменился. Начните добавление заново.')
        # The bot may restart during fleet commit. Completion is persisted outside
        # its process and delivered on its next startup; never replay enrollment.
        output=io.StringIO()
        with redirect_stdout(output):connect.complete(current,value['code'],current['fleet_profile'],value['name'])
        message=output.getvalue()[-3000:]
    # Archive new account config/pins and the updated roster after registration.
    try:message+='\nПроверенная зашифрованная копия: '+str(backup.create())
    except Exception:message+='\nРегистрация завершена; создание бэкапа не удалось. Повторите кнопкой «Создать бэкап».'
    return message

def consume():
    config=load_config(CONFIG)
    path=INBOX/'request.json'
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:return
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=pwd.getpwnam('xtlsrouterbot').pw_uid or info.st_size>4096:raise ValueError('unsafe request')
        with os.fdopen(fd,'rb',closefd=False) as stream:body=stream.read(4097)
        if len(body)>4096:raise ValueError('size')
        value=validate(json.loads(body),config)
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)
    target=RESULTS/(value['id']+'.json')
    if target.exists():return  # UUIDs are single-use even after daemon restart.
    rate=RESULTS/('last-'+value['action'])
    interval=60 if value['action']=='backup' else 20
    if rate.exists() and time.time()-rate.stat().st_mtime<interval:
        save({'id':value['id'],'state':'failed','text':'Подождите минуту перед повторной операцией.'});return
    rate.touch(mode=0o600)
    save({'id':value['id'],'state':'running'})
    try:
        message=execute(value,config)
        save({'id':value['id'],'state':'done','text':message})
    except SafeError as error:save({'id':value['id'],'state':'failed','text':'Операция остановлена: '+str(error)})
    except Exception:save({'id':value['id'],'state':'failed','text':'Операция не завершена. Проверьте службу и доступность роутера. Автоматического повтора нет.'})
    # Retain receipts for replay prevention; no request codes/tokens are stored.

def main():
    if os.geteuid()!=0:raise ValueError('root required')
    os.umask(0o077)
    with open(RESULTS/'worker.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        consume()

if __name__=='__main__':
    try:main()
    except Exception:
        print('Operator request rejected; no arbitrary commands are supported.')
        raise SystemExit(1)
