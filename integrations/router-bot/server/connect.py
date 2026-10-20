#!/usr/bin/python3
"""Two-command operator enrollment, without a public listener or password login."""
import argparse
import base64
from contextlib import contextmanager, redirect_stdout
import fcntl
import hashlib
import ipaddress
import io
import json
import os
from pathlib import Path
import pwd
import re
import resource
import shlex
import subprocess
import tempfile
import fleet
from bot import SafeError, load_config

BOOTSTRAP_REF='219b4a43395122635c06f56827a5ad196586613b'
BOOTSTRAP_SHA='3860e4125ddd49d4830b1d81bfcdd9d189543626b40b38fe8bf12dc3ba3c4d8d'
BOOTSTRAP_URL='https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/'+BOOTSTRAP_REF+'/integrations/router-bot/router/join.sh'


def pairing(code):
    if not isinstance(code,str) or len(code)>150:raise SafeError('Некорректный код роутера.')
    m=re.fullmatch(r'xtls-pair-v1:([0-9.]+):([0-9]{1,5}):([A-Za-z0-9+/]{43})',code)
    if not m:raise SafeError('Ожидался короткий код xtls-pair-v1 из команды роутера.')
    try:host=ipaddress.ip_address(m[1])
    except ValueError:raise SafeError('Некорректный адрес роутера.') from None
    if host.version!=4 or host not in ipaddress.ip_network('100.64.0.0/10') or not 1<=int(m[2])<=65535:raise SafeError('Нужны адрес NetBird и SSH-порт роутера.')
    return {'host':str(host),'port':int(m[2]),'fingerprint':m[3]}


def fingerprint(public):
    fleet.key(public)
    return base64.b64encode(hashlib.sha256(base64.b64decode(public.split()[1],validate=True)).digest()).decode().rstrip('=')


def scanned_key(output,expected):
    keys=[]
    for line in output.splitlines():
        if not line or line.startswith('#'):continue
        parts=line.split()
        if len(parts)!=3 or parts[1]!='ssh-ed25519':raise SafeError('Некорректный ответ SSH-keyscan.')
        public=' '.join(parts[1:]);fleet.key(public)
        if public not in keys:keys.append(public)
    if len(keys)!=1 or fingerprint(keys[0])!=expected:raise SafeError('Отпечаток SSH не совпал с кодом роутера. Подключение остановлено.')
    return keys[0]


def scan_key(pair):
    with tempfile.TemporaryFile() as output:
        result=subprocess.run(['runuser','-u','xtlsrouterbot','--','ssh-keyscan','-T','4','-t','ed25519','-p',str(pair['port']),pair['host']],stdout=output,stderr=subprocess.DEVNULL,timeout=8,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_FSIZE,(16384,16384)))
        output.seek(0);body=output.read(8193)
    if result.returncode or len(body)>8192:raise SafeError('SSH роутера недоступен через NetBird. Проверь адрес, порт и политику доступа.')
    try:text=body.decode('ascii')
    except UnicodeError:raise SafeError('Некорректный ответ SSH-keyscan.') from None
    return scanned_key(text,pair['fingerprint'])


def router_command(profile):
    fields=('schema','profile_id','bot_public_key','rescue_host','rescue_port','rescue_host_key')
    public={field:profile[field] for field in fields}
    payload='xtls-profile-v1:'+base64.b64encode(json.dumps(public,separators=(',',':')).encode()).decode()
    # Keep physical input lines short for BusyBox ash and terminal paste limits.
    lines=['clear','(', '    set -e', '    umask 077',
        '    work=$(mktemp -d /tmp/xtls-bot-pair.XXXXXX)',
        "    trap 'rm -rf \"$work\"' EXIT",
        '    curl -fL --connect-timeout 10 --max-time 60 \\',
        '        '+shlex.quote(BOOTSTRAP_URL)+' \\',
        '        -o "$work/join.sh"',
        "    printf '%s  %s\\n' "+shlex.quote(BOOTSTRAP_SHA)+' "$work/join.sh" | sha256sum -c -',
        "    profile=''" ]
    for offset in range(0,len(payload),120):
        lines.append('    profile="$profile"'+shlex.quote(payload[offset:offset+120]))
    lines.extend(['    sh "$work/join.sh" "$profile"',')'])
    return '\n'.join(lines)



@contextmanager
def lock():
    with open('/run/xtls-router-fleet.lock','w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def public_profile(config,host=None,port=None):
    saved=config.get('fleet_profile')
    host=host or (saved or {}).get('rescue_host')
    port=port if port is not None else (saved or {}).get('rescue_port',62152)
    if not host:raise SafeError('При первом запуске укажи --host ПУБЛИЧНЫЙ_IP_VPS и при необходимости --port SSH_ПОРТ.')
    with tempfile.TemporaryDirectory(prefix='xtls-connect-profile-') as directory:
        output=Path(directory)/'profile.json'
        with redirect_stdout(io.StringIO()):fleet.profile_command(config,host,port,output)
        return json.loads(output.read_text())


def resolve(config,pair,profile):
    print('Проверяем отпечаток SSH и идентичность роутера…',flush=True)
    public=scan_key(pair)
    known=Path(config['known_hosts'])
    pinned=fleet.pinned(known.read_text(),{**pair,'host_key':public},None)
    user=pwd.getpwnam('xtlsrouterbot')
    fd,path=tempfile.mkstemp(prefix='.connect-probe-',dir=known.parent);os.close(fd);path=Path(path)
    try:
        fleet.atomic(path,pinned,0o600,(user.pw_uid,user.pw_gid))
        data=fleet.remote(config,pair,path,'xtlsbot-v1 identity')
        p=fleet.passport(data,profile)
        if p['host']!=pair['host'] or p['port']!=pair['port'] or p['host_key']!=public:raise SafeError('Идентичность SSH не соответствует коду подключения.')
        return p
    finally:path.unlink(missing_ok=True)


def legacy_router(config,p):
    matches=[rid for rid,r in config['routers'].items() if r['host']==p['host'] and r['port']==p['port']]
    if len(matches)>1:raise SafeError('Адрес совпадает с несколькими записями. Проверь реестр.')
    # Existing host pin and UUID are checked by fleet.enroll; no blind replacement.
    return matches[0] if matches else None


def complete(config,code,profile,name=None):
    pair=pairing(code)
    p=resolve(config,pair,profile)
    rid=legacy_router(config,p)
    print('Устройство:',p['model'],'· UUID',p['device_id'],flush=True)
    if rid:print('Используем существующую запись:',rid,'; клиентские доступы сохраняются.',flush=True)
    fleet.enroll(config,p,rid,name)
    print('Готово. Открой карточку роутера в боте; доступ клиенту выдаётся кнопкой «Доступ клиентов».')


def main():
    parser=argparse.ArgumentParser(description='Подключить настроенный роутер к существующему боту двумя командами.')
    parser.add_argument('--host',help='Публичный IPv4 VPS, только для первого профиля')
    parser.add_argument('--port',type=int,help='SSH-порт VPS, только для первого профиля')
    parser.add_argument('--name',help='Имя нового роутера; существующее имя сохраняется по умолчанию')
    parser.add_argument('--code',help='Повторно использовать уже полученный короткий код без интерактивного ввода')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SafeError('Запусти xtls-router-add от root на VPS бота.')
    os.umask(0o077)
    with lock():
        config=load_config(fleet.CONFIG)
        profile=public_profile(config,args.host,args.port)
    if not args.code:
        print('\n1. В другой SSH-вкладке на роутере выполни целиком эту команду:\n')
        print(router_command(profile),flush=True)
        print('\n2. Скопируй короткий код xtls-pair-v1 с роутера и вставь сюда.\nПароль SSH, setup key и Telegram-токен не нужны.\n')
        try:code=input('Код роутера: ').strip()
        except EOFError:raise SafeError('Код не введён. Запусти мастер в интерактивной SSH-сессии.') from None
    else:code=args.code
    # Do not hold the fleet lock while the operator prepares the router.
    with lock():
        config=load_config(fleet.CONFIG)
        if config.get('fleet_profile')!=profile:raise SafeError('Профиль VPS изменился. Запусти мастер заново.')
        complete(config,code,profile,args.name)


if __name__=='__main__':
    try:main()
    except (KeyboardInterrupt,EOFError):print('\nПодключение отменено.');raise SystemExit(130)
    except SafeError as error:print('Остановка:',error);raise SystemExit(1)
    except BlockingIOError:print('Другая регистрация выполняется. Повтори после её завершения.');raise SystemExit(1)
    except Exception:print('Подключение не завершено. Проверь NetBird, SSH и состояние службы; секреты не выводятся.');raise SystemExit(1)
