#!/usr/bin/python3
"""Operator-only enrollment. Public passports are not client access credentials."""
import argparse
import base64
from contextlib import contextmanager
import copy
import fcntl
import ipaddress
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import resource
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import uuid
from bot import SafeError, load_config, ssh_command

CONFIG=Path('/etc/xtls-router-bot/config.json')
SSHD_DIR=Path('/etc/ssh/sshd_config.d')
UNIT='xtls-router-bot'


def key(value):
    if not isinstance(value,str):raise SafeError('Ожидался публичный ключ.')
    parts=value.split()
    if len(parts)!=2 or parts[0]!='ssh-ed25519':raise SafeError('Ожидался публичный ключ Ed25519 без комментария.')
    try:raw=base64.b64decode(parts[1],validate=True)
    except ValueError:raise SafeError('Некорректный публичный ключ.') from None
    if len(raw)!=51 or raw[:19]!=b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':raise SafeError('Некорректный публичный ключ.')
    return value


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value):raise SafeError('Некорректный идентификатор устройства.')
    return value


def passport(data, profile):
    if not isinstance(data,dict) or data.get('schema')!=1 or data.get('profile_id')!=profile['profile_id']:raise SafeError('Паспорт относится к другому профилю VPS.')
    identifier(data.get('device_id'))
    try:host=ipaddress.ip_address(data.get('host',''))
    except ValueError:raise SafeError('Нет корректного адреса NetBird.') from None
    if host.version!=4 or host not in ipaddress.ip_network('100.64.0.0/10'):raise SafeError('Ожидался адрес NetBird.')
    if type(data.get('port')) is not int or not 1<=data['port']<=65535:raise SafeError('Некорректный SSH-порт.')
    key(data.get('host_key'));key(data.get('rescue_public_key'))
    if not isinstance(data.get('model'),str) or not 1<=len(data['model'])<=120 or any(ord(c)<32 or ord(c)==127 for c in data['model']):raise SafeError('Некорректная модель.')
    return {k:data[k] for k in ('schema','profile_id','device_id','model','host','port','host_key','rescue_public_key')}


def decode(code):
    if not isinstance(code,str) or len(code)>8192 or not code.startswith('xtls-enroll-v1:'):raise SafeError('Некорректный код подключения.')
    try:return json.loads(base64.b64decode(code.split(':',1)[1],validate=True))
    except (ValueError,UnicodeError):raise SafeError('Код подключения повреждён.') from None


def choose(config,p,requested=None,name=None):
    routers=config['routers'];device=p['device_id']
    matches=[rid for rid,r in routers.items() if r.get('device_id')==device]
    if len(matches)>1:raise SafeError('UUID уже дублируется в реестре.')
    rid=matches[0] if matches else requested or 'r-'+hashlib.sha256(device.encode()).hexdigest()[:20]
    if requested and matches and requested!=rid:raise SafeError('Устройство уже имеет другой ID.')
    if not re.fullmatch(r'[a-z0-9_-]{1,32}',rid):raise SafeError('Некорректный ID роутера.')
    if rid in routers:
        old=routers[rid]
        if old.get('device_id') not in (None,device) or old['host']!=p['host'] or old['port']!=p['port']:raise SafeError('ID уже занят другим устройством; автоматическая замена запрещена.')
        if old.get('fleet') and old['fleet']['host_key']!=p['host_key']:raise SafeError('Серверный ключ роутера изменился.')
    for other,r in routers.items():
        if other!=rid and (r['host']==p['host'] or r.get('device_id')==device or r.get('fleet',{}).get('host_key')==p['host_key']):raise SafeError('Адрес, UUID или SSH-ключ уже закреплён за другим роутером.')
    if name is None:name=routers.get(rid,{}).get('name') or p['model']+' · '+device[:8]
    if not isinstance(name,str) or not 1<=len(name)<=100 or any(ord(c)<32 or ord(c)==127 for c in name):raise SafeError('Имя: 1–100 символов без управляющих знаков.')
    return rid,name


def pinned(known,p,port):
    primary=p['host'] if p['port']==22 else '['+p['host']+']:'+str(p['port'])
    entries={primary:p['host_key']}
    if port is not None:entries['[127.0.0.1]:'+str(port)]=p['host_key']
    lines=known.splitlines()
    for host,expected in entries.items():
        for line in lines:
            parts=line.split()
            if not parts or line.startswith('#'):continue
            marked=parts[0].startswith('@');names=parts[1] if marked and len(parts)>1 else parts[0]
            matches=host in names.split(',')
            if names.startswith('|1|'):
                try:
                    _,_,salt,digest=names.split('|');calculated=hmac.new(base64.b64decode(salt),host.encode(),hashlib.sha1).digest()
                    matches=hmac.compare_digest(calculated,base64.b64decode(digest))
                except (ValueError,TypeError):raise SafeError('Повреждён хешированный known_hosts.') from None
            if matches and (marked or ' '.join(parts[1:3])!=expected):raise SafeError('В known_hosts закреплён другой ключ. Проверь устройство вручную.')
        entry=host+' '+expected
        if not any(line.split()[:3]==entry.split() for line in lines):lines.append(entry)
    return '\n'.join(lines)+'\n'


def free_port(config):
    reserved={r.get('rescue',{}).get('port') for r in config['routers'].values()}
    for file in SSHD_DIR.glob('*.conf'):
        reserved.update(int(p) for p in re.findall(r'(?im)^\s*PermitListen\s+127\.0\.0\.1:([0-9]+)\s*$',file.read_text()))
    for port in range(22001,30000):
        if port in reserved:continue
        try:
            with socket.socket() as sock:sock.bind(('127.0.0.1',port))
        except OSError:continue
        return port
    raise SafeError('Свободных аварийных портов нет.')


def relay_text(account,port):
    if not re.fullmatch(r'xtls-r-[a-f0-9]{12}',account) or not 22001<=port<=29999:raise SafeError('Некорректный аварийный пользователь или порт.')
    return f'''Match User {account}
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthorizedKeysFile .ssh/authorized_keys
    AllowTcpForwarding remote
    DisableForwarding no
    ClientAliveInterval 30
    ClientAliveCountMax 3
    AllowStreamLocalForwarding no
    PermitListen 127.0.0.1:{port}
    PermitOpen none
    GatewayPorts no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    PermitTunnel no
    PermitUserRC no
    MaxSessions 0
Match all
'''


def atomic(path,content,mode=None,owner=None):
    if path.is_symlink():raise SafeError('Символьная ссылка вместо файла — остановка.')
    info=path.stat() if path.exists() else None
    fd,tmp=tempfile.mkstemp(prefix='.fleet-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:out.write(content)
        os.chmod(tmp,mode if mode is not None else info.st_mode&0o777 if info else 0o600)
        target=owner or ((info.st_uid,info.st_gid) if info else (0,0))
        os.chown(tmp,*target);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def command(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=30)


@contextmanager
def db_owner(database):
    user=pwd.getpwnam('xtlsrouterbot');gid=os.getegid();groups=os.getgroups()
    try:
        os.setgroups([]);os.setegid(user.pw_gid);os.seteuid(user.pw_uid)
        yield
    finally:
        os.seteuid(0);os.setegid(gid);os.setgroups(groups)


def remote(config,router,pins,operation,input_data=None):
    # Closed, root-constructed commands; never interpolate operator text in SSH.
    if operation!='xtlsbot-v1 identity' and not re.fullmatch(r'xtlsbot-v1 enroll-(apply|commit|rollback) [a-f0-9-]{36} [a-f0-9-]{36}',operation):raise SafeError('Некорректная команда регистрации.')
    local={**config,'known_hosts':str(pins)}
    with tempfile.TemporaryFile() as output:
        result=subprocess.run(['runuser','-u','xtlsrouterbot','--',*ssh_command(local,router,operation)],input=json.dumps(input_data).encode() if input_data is not None else b'',stdout=output,stderr=subprocess.DEVNULL,timeout=40,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_FSIZE,(16384,16384)))
        output.seek(0);body=output.read(8193)
    if len(body)>8192:raise SafeError('Превышен размер ответа регистрации.')
    try:reply=json.loads(body)
    except ValueError:raise SafeError('Роутер не подтвердил регистрацию по SSH.') from None
    if result.returncode or not isinstance(reply,dict) or reply.get('schema')!=1 or reply.get('ok') is not True or not isinstance(reply.get('data'),dict):raise SafeError('Проверка SSH устройства не пройдена.')
    return reply['data']


def verify_identity(config,router,pins,p):
    actual=remote(config,router,pins,'xtlsbot-v1 identity')
    for field in ('device_id','profile_id','host','port','host_key','rescue_public_key'):
        if actual.get(field)!=p[field]:raise SafeError('SSH ответил другим устройством. Регистрация остановлена.')
    return actual


def shared_relay_homes(path):
    if path.is_symlink():raise SafeError('Небезопасный каталог аварийных пользователей.')
    path.mkdir(mode=0o755,exist_ok=True)
    if path.stat().st_uid!=os.geteuid():raise SafeError('Неверный владелец каталога аварийных пользователей.')
    # mkdir's mode is filtered by the operator's mandatory umask 077.
    # Each private home stays protected; users must traverse this shared parent.
    os.chmod(path,0o755)


def enrollment_port(config,account,device_id):
    saved=SSHD_DIR/('65-xtls-fleet-'+account+'.conf')
    if not saved.exists():return free_port(config)
    if saved.is_symlink():raise SafeError('Небезопасный файл ограничений SSH.')
    body=saved.read_text()
    ports=re.findall(r'(?m)^    PermitListen 127\.0\.0\.1:([0-9]+)$',body)
    if len(ports)!=1:raise SafeError('Сохранённый аварийный порт не определён.')
    port=int(ports[0])
    if body!=relay_text(account,port):raise SafeError('Ограничения аварийного пользователя отличаются.')
    try:user=pwd.getpwnam(account)
    except KeyError:raise SafeError('Сохранённый аварийный пользователь отсутствует.') from None
    marker=Path(user.pw_dir)/'.xtls-fleet-device'
    if marker.is_symlink() or not marker.is_file() or marker.read_text().strip()!=device_id:raise SafeError('Аварийный пользователь относится к другому UUID.')
    if any(r.get('rescue',{}).get('port')==port for r in config['routers'].values()):raise SafeError('Сохранённый аварийный порт уже закреплён в реестре.')
    return port


def relay(account,port,public_key,device_id):
    config=SSHD_DIR/('65-xtls-fleet-'+account+'.conf')
    body=relay_text(account,port)
    created=False
    homes=Path('/var/lib/xtls-router-rescue')
    shared_relay_homes(homes)
    try:user=pwd.getpwnam(account)
    except KeyError:
        command('useradd','--system','--user-group','--create-home','--home-dir','/var/lib/xtls-router-rescue/'+account,'--shell','/usr/sbin/nologin',account)
        user=pwd.getpwnam(account);created=True
    marker=Path(user.pw_dir)/'.xtls-fleet-device'
    if not created and (not marker.is_file() or marker.is_symlink() or marker.read_text().strip()!=device_id):raise SafeError('Аварийная учётная запись не принадлежит этому UUID.')
    if not created and (user.pw_dir!='/var/lib/xtls-router-rescue/'+account or user.pw_shell!='/usr/sbin/nologin'):raise SafeError('Имя аварийного пользователя занято посторонней учётной записью.')
    auth=Path(user.pw_dir)/'.ssh/authorized_keys'
    entry='restrict,port-forwarding,permitlisten="127.0.0.1:'+str(port)+'" '+key(public_key)+' xtls-router-rescue\n'
    if config.exists() and config.read_text()!=body:raise SafeError('Ограничения SSH пользователя отличаются — остановка.')
    if auth.exists() and auth.read_text() not in ('',entry):raise SafeError('Ключ аварийного пользователя отличается — остановка.')
    atomic(marker,device_id+'\n',0o600)
    ssh=auth.parent
    if ssh.is_symlink():raise SafeError('Небезопасный каталог ключей.')
    ssh.mkdir(mode=0o700,exist_ok=True);os.chown(ssh,user.pw_uid,user.pw_gid);os.chmod(ssh,0o700)
    atomic(auth,entry,0o600,(user.pw_uid,user.pw_gid))
    SSHD_DIR.mkdir(parents=True,exist_ok=True)
    atomic(config,body,0o600)
    try:
        command('/usr/sbin/sshd','-t')
        result=command('/usr/sbin/sshd','-T','-C','user='+account+',host=localhost,addr=127.0.0.1').stdout.splitlines()
        for expected in ('authenticationmethods publickey','disableforwarding no','allowtcpforwarding remote','permitlisten 127.0.0.1:'+str(port),'permitopen none','gatewayports no','maxsessions 0','passwordauthentication no'):
            if expected not in result:raise SafeError('Ограничение SSH не применилось: '+expected)
        command('systemctl','reload','ssh')
    except Exception:
        # Keep an inert account for inspection; never delete an existing account.
        if created:
            atomic(auth,'',0o600,(user.pw_uid,user.pw_gid))
            config.unlink(missing_ok=True)
        raise
    return config,auth,created


def profile_command(config,host,port,output):
    address=ipaddress.ip_address(host)
    if address.version!=4 or not address.is_global or not 1<=port<=65535:raise SafeError('Нужен публичный IPv4 VPS и SSH-порт.')
    host_key=' '.join(Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()[:2]);key(host_key)
    bot_key=' '.join(command('runuser','-u','xtlsrouterbot','--','ssh-keygen','-y','-f',config['ssh_key']).stdout.split()[:2]);key(bot_key)
    old=config.get('fleet_profile')
    value={'schema':1,'profile_id':old['profile_id'] if old else str(uuid.uuid4()),'bot_public_key':bot_key,'rescue_host':host,'rescue_port':port,'rescue_host_key':host_key}
    if old and old!=value:raise SafeError('Профиль VPS изменился. Миграция требует отдельной проверки.')
    if output.exists() and output.read_text()!=json.dumps(value,ensure_ascii=False,indent=2)+'\n':raise SafeError('Выходной файл уже содержит другой профиль.')
    if not old:
        backup=Path(tempfile.mkdtemp(prefix='/root/xtls-before-fleet-profile-'));shutil.copy2(CONFIG,backup/'config.json')
        config['fleet_profile']=value;atomic(CONFIG,json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    atomic(output,json.dumps(value,ensure_ascii=False,indent=2)+'\n',0o600)
    print('Публичный профиль:',output)


def enroll(config,p,requested,name):
    original_config=CONFIG.read_text()
    if json.loads(original_config)!=config:raise SafeError('Конфигурация изменилась. Повтори регистрацию.')
    rid,label=choose(config,p,requested,name)
    old=config['routers'].get(rid,{})
    existing=old.get('fleet')
    account=existing['account'] if existing else 'xtls-r-'+hashlib.sha256(p['device_id'].encode()).hexdigest()[:12]
    port=old['rescue']['port'] if existing else enrollment_port(config,account,p['device_id'])
    pins=Path(config['known_hosts']);original_pins=pins.read_text();candidate_pins=pinned(original_pins,p,port)
    user=pwd.getpwnam('xtlsrouterbot')
    fd,probe=tempfile.mkstemp(prefix='.fleet-probe-',dir=pins.parent);os.close(fd);probe=Path(probe)
    tx=existing['transaction'] if existing else str(uuid.uuid4());applied=False;started=False;backup=None;commit_started=False
    primary={'host':p['host'],'port':p['port']}
    try:
        atomic(probe,candidate_pins,0o600,(user.pw_uid,user.pw_gid))
        actual=verify_identity(config,primary,probe,p)
        recovered=actual.get('enrollment') or {}
        if not existing and recovered.get('state') in ('pending','enrolled'):
            if recovered.get('user')!=account or type(recovered.get('remote_port')) is not int or not 22001<=recovered['remote_port']<=29999:raise SafeError('Сохранённая регистрация устройства не соответствует реестру.')
            for other,r in config['routers'].items():
                if other!=rid and r.get('rescue',{}).get('port')==recovered['remote_port']:raise SafeError('Сохранённый аварийный порт занят другим роутером.')
            port=recovered['remote_port'];tx=identifier(recovered.get('transaction'))
            candidate_pins=pinned(original_pins,p,port)
            atomic(probe,candidate_pins,0o600,(user.pw_uid,user.pw_gid))
        if existing:
            state=actual.get('enrollment') or {}
            if state.get('transaction')!=tx or state.get('state') not in ('pending','enrolled') or state.get('user')!=account or state.get('remote_port')!=port:raise SafeError('Реестр VPS и состояние регистрации роутера расходятся.')
        if not existing and not requested:
            for other,r in config['routers'].items():
                if r['host']==p['host']:raise SafeError('Устройство уже записано как '+other+'; используй --router '+other)
        relay(account,port,p['rescue_public_key'],p['device_id'])
        if not existing and recovered.get('state')!='enrolled':
            # Fence the broker before replacing a tunnel it may be using.
            backup=Path(tempfile.mkdtemp(prefix='/root/xtls-before-fleet-enroll-'))
            shutil.copy2(CONFIG,backup/'config.json');shutil.copy2(pins,backup/'known_hosts')
            database=config['database']
            with db_owner(database):
                db=sqlite3.connect(database,timeout=10);db.execute('BEGIN IMMEDIATE')
                busy=db.execute("SELECT count(*) FROM operations WHERE state='running'").fetchone()[0]
            try:
                if busy:raise SafeError('Выполняется операция роутера. Дождись её окончания.')
                command('systemctl','stop',UNIT);started=True
            finally:
                with db_owner(database):db.rollback();db.close()
            applied=True
            remote(config,primary,probe,'xtlsbot-v1 enroll-apply '+p['device_id']+' '+tx,{'profile_id':p['profile_id'],'transaction':tx,'user':account,'remote_port':port,'local_port':p['port']})
        if existing or recovered.get('state')=='enrolled':
            # A healthy router closes its standby tunnel. Re-open it explicitly
            # before verifying an existing registration; never reapply enrollment.
            opened=remote(config,primary,probe,'xtlsbot-v1 admin-open-rescue')
            if opened.get('ok') is not True:raise SafeError('Не удалось открыть аварийный канал для проверки.')
        deadline=time.monotonic()+50
        rescue={'host':'127.0.0.1','port':port}
        while True:
            try:verify_identity(config,rescue,probe,p);break
            except (SafeError,subprocess.TimeoutExpired):
                if time.monotonic()>=deadline:raise SafeError('Аварийный путь не подтвердился.') from None
                time.sleep(2)
        if existing and actual['enrollment']['state']=='enrolled' and label==old['name']:
            print('Устройство уже подключено:',rid,'· аварийный порт',port,'; повторных записей нет.')
            return
        candidate=copy.deepcopy(config)
        candidate['routers'][rid]={**old,'name':label,**primary,'device_id':p['device_id'],'rescue':rescue,'fleet':existing or {'account':account,'host_key':p['host_key'],'rescue_public_key':p['rescue_public_key'],'profile_id':p['profile_id'],'transaction':tx}}
        if not backup:
            backup=Path(tempfile.mkdtemp(prefix='/root/xtls-before-fleet-enroll-'))
            shutil.copy2(CONFIG,backup/'config.json');shutil.copy2(pins,backup/'known_hosts')
        check=backup/'candidate.json';check.write_text(json.dumps(candidate));load_config(check)
        if CONFIG.read_text()!=original_config or pins.read_text()!=original_pins:raise SafeError('Конфигурация или ключи изменились во время проверки. Повтори регистрацию.')
        if not started:
            # Stop dispatch before mutating an existing rescue path.
            database=config['database']
            with db_owner(database):
                db=sqlite3.connect(database,timeout=10);db.execute('BEGIN IMMEDIATE')
                busy=db.execute("SELECT count(*) FROM operations WHERE state='running'").fetchone()[0]
            try:
                if busy:raise SafeError('Выполняется операция роутера. Дождись её окончания.')
                command('systemctl','stop',UNIT);started=True
            finally:
                with db_owner(database):db.rollback();db.close()
        atomic(pins,candidate_pins)
        atomic(CONFIG,json.dumps(candidate,ensure_ascii=False,indent=2)+'\n')
        command('systemctl','start',UNIT);time.sleep(3);command('systemctl','is-active','--quiet',UNIT)
        if applied or existing and actual['enrollment']['state']=='pending':
            commit_started=True
            try:remote(config,primary,probe,'xtlsbot-v1 enroll-commit '+p['device_id']+' '+tx)
            except Exception:
                confirmed=verify_identity(config,rescue,probe,p).get('enrollment') or {}
                if confirmed.get('transaction')!=tx or confirmed.get('state')!='enrolled':raise SafeError('Фиксация регистрации не подтверждена; запись сохранена для повторной сверки.') from None
            applied=False;commit_started=False
        with db_owner(config['database']):
            with sqlite3.connect(config['database']) as db:
                row=db.execute('SELECT seq FROM router_ids WHERE router=?',(rid,)).fetchone()
        display=('R-'+str(row[0]).zfill(6)) if row else rid
        print('Роутер подключён:',display,rid,'·',label,'· аварийный порт',port)
        print('Назначь Telegram-клиенту доступ через меню «Доступ клиентов». Подписка сама доступ не выдаёт.')
        print('Резервная копия:',backup)
    except Exception:
        if commit_started:
            print('Запись VPS сохранена. Повтори ту же регистрацию для сверки; настройки устройства не перезаписываются.')
            raise
        if started and backup:
            command('systemctl','stop',UNIT)
            atomic(CONFIG,(backup/'config.json').read_text());atomic(pins,(backup/'known_hosts').read_text())
            command('systemctl','start',UNIT)
        if applied:
            try:remote(config,primary,probe,'xtlsbot-v1 enroll-rollback '+p['device_id']+' '+tx)
            except Exception:print('Откат на роутере не подтверждён. Основной NetBird не изменялся; проверь регистрацию вручную.')
        raise
    finally:probe.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='action',required=True)
    profile=sub.add_parser('profile');profile.add_argument('--host',required=True);profile.add_argument('--port',type=int,default=62152);profile.add_argument('--output',type=Path,required=True)
    add=sub.add_parser('enroll');group=add.add_mutually_exclusive_group(required=True);group.add_argument('--code');group.add_argument('--passport',type=Path);add.add_argument('--router');add.add_argument('--name')
    sub.add_parser('list')
    sub.add_parser('rebuild-relay')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SafeError('Запусти команду от root на VPS бота.')
    os.umask(0o077)
    with open('/run/xtls-router-fleet.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        config=load_config(CONFIG)
        if args.action=='profile':profile_command(config,args.host,args.port,args.output)
        elif args.action=='rebuild-relay':
            saved=config.get('fleet_profile')
            current=' '.join(Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()[:2])
            if not saved or saved['rescue_host_key']!=current:raise SafeError('SSH-ключ VPS отличается от сохранённого. Сначала подготовь явную миграцию профилей.')
            for rid,r in config['routers'].items():
                if r.get('fleet'):
                    info=r['fleet'];relay(info['account'],r['rescue']['port'],info['rescue_public_key'],r['device_id'])
            print('Ограниченные аварийные пользователи восстановлены из реестра.')
        elif args.action=='list':
            with db_owner(config['database']):
                with sqlite3.connect(config['database']) as db:
                    codes=dict(db.execute('SELECT router,seq FROM router_ids'))
            for rid,r in config['routers'].items():print('R-'+str(codes[rid]).zfill(6) if rid in codes else rid,r['name'],r.get('device_id','legacy'),r.get('rescue',{}).get('port','—'))
        else:
            profile=config.get('fleet_profile')
            if not profile:raise SafeError('Сначала создай публичный профиль VPS.')
            if args.passport and (not args.passport.is_file() or args.passport.is_symlink() or args.passport.stat().st_size>8192):raise SafeError('Ожидался публичный паспорт до 8 КиБ.')
            data=decode(args.code) if args.code else json.loads(args.passport.read_text())
            enroll(config,passport(data,profile),args.router,args.name)


if __name__=='__main__':
    try:main()
    except SafeError as error:print('Остановка:',error);raise SystemExit(1)
    except Exception:print('Регистрация не завершена. Проверь службу и SSH; секреты не выводятся.');raise SystemExit(1)
