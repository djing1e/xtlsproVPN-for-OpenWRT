#!/usr/bin/python3
"""Administrator and client router pilot. No arbitrary SSH or Telegram shell commands."""
import concurrent.futures
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import math
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request

LOG = logging.getLogger('xtls-router-bot')
NODE = re.compile(r'cfg[A-Za-z0-9_-]{6}\Z')
SUPPORT_URL = 'https://t.me/xtlsprosupportbot'
JOB = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z')


class SafeError(Exception):
    """Only fixed, safe messages may reach the user or journal."""
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class Telegram:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method, **payload):
        request = urllib.request.Request(
            'https://api.telegram.org/bot' + self.token + '/' + method,
            data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=40) as response:
                result = json.loads(response.read(2_000_001))
            if not result.get('ok'):
                raise SafeError('Telegram отклонил запрос.', result.get('error_code'))
            return result['result']
        except urllib.error.HTTPError as error:
            raise SafeError('Telegram отклонил запрос.', error.code) from None
        except (OSError, ValueError, urllib.error.URLError):
            # urllib exceptions include the token-bearing URL. Never log them.
            raise SafeError('Telegram временно недоступен.') from None


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER);
                CREATE TABLE IF NOT EXISTS buttons (
                    token TEXT PRIMARY KEY, uid INTEGER, router TEXT, action TEXT,
                    target TEXT, expires INTEGER, used INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS operations (
                    update_id INTEGER PRIMARY KEY, uid INTEGER, router TEXT,
                    action TEXT, target TEXT, state TEXT, job TEXT, created INTEGER);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(buttons)')}
            if 'grant_epoch' not in columns:
                db.execute("ALTER TABLE buttons ADD COLUMN grant_epoch TEXT NOT NULL DEFAULT ''")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS grants (
                    uid INTEGER, router TEXT, epoch TEXT NOT NULL, created INTEGER,
                    PRIMARY KEY(uid,router));
                CREATE TABLE IF NOT EXISTS router_ids (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, router TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS user_ids (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER UNIQUE NOT NULL,
                    name TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS monitoring (
                    router TEXT PRIMARY KEY, enabled INTEGER DEFAULT 0,
                    failures INTEGER DEFAULT 0, offline INTEGER DEFAULT 0, checked INTEGER,
                    proxy_failures INTEGER DEFAULT 0, last_health INTEGER DEFAULT 0, proxy_bad INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS monitor_events (
                    id INTEGER PRIMARY KEY, router TEXT, offline INTEGER,
                    state TEXT DEFAULT 'pending', kind TEXT DEFAULT 'ssh');
                CREATE TABLE IF NOT EXISTS router_subscriptions (
                    router TEXT PRIMARY KEY, subscription_id TEXT, updated INTEGER);
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY, uid INTEGER, router TEXT, granted INTEGER,
                    epoch TEXT, state TEXT DEFAULT 'pending', retry_at INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS router_presence (
                    router TEXT PRIMARY KEY, reachable INTEGER NOT NULL, checked REAL NOT NULL,
                    last_seen REAL, transport TEXT);
                CREATE TABLE IF NOT EXISTS router_names (
                    router TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS router_hwids (
                    router TEXT PRIMARY KEY, hwid TEXT, updated INTEGER);
                CREATE TABLE IF NOT EXISTS operator_dialogs (
                    uid INTEGER PRIMARY KEY, stage TEXT, name TEXT, expires INTEGER);
                CREATE TABLE IF NOT EXISTS operator_jobs (
                    id TEXT PRIMARY KEY, uid INTEGER, action TEXT, created INTEGER,
                    state TEXT, text TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS catalog_sessions (
                    uid INTEGER PRIMARY KEY, query TEXT, page INTEGER, awaiting INTEGER, expires INTEGER);
                CREATE TABLE IF NOT EXISTS input_dialogs (
                    uid INTEGER PRIMARY KEY, router TEXT, expires INTEGER);
                CREATE TABLE IF NOT EXISTS access_audit (
                    id INTEGER PRIMARY KEY, actor INTEGER, uid INTEGER,
                    router TEXT, action TEXT, created INTEGER);
            ''')
            # A lost process must never replay an SSH mutation after a restart.
            db.execute("UPDATE operations SET state='interrupted' WHERE state='running'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def catalog(self, uid, query=None, page=0, awaiting=False):
        with self.connect() as db:
            if query is not None:
                db.execute('INSERT OR REPLACE INTO catalog_sessions VALUES (?,?,?,?,?)',
                           (uid, query, page, int(awaiting), int(time.time()) + 900))
            row = db.execute('SELECT * FROM catalog_sessions WHERE uid=? AND expires>?',
                             (uid, int(time.time()))).fetchone()
            return dict(row) if row else {'query': '', 'page': 0, 'awaiting': 0}

    def catalog_metadata(self):
        with self.connect() as db:
            hwids = {r['router']: r['hwid'] or '' for r in db.execute('SELECT router,hwid FROM router_hwids')}
            numbers = {r['router']: r['subscription_id'] or '' for r in db.execute('SELECT router,subscription_id FROM router_subscriptions')}
        return hwids, numbers

    def offset(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
            return row[0] if row else 0

    def checkpoint(self, update_id):
        with self.connect() as db:
            db.execute("INSERT INTO meta VALUES ('offset',?) ON CONFLICT(key) DO UPDATE SET value=max(value,excluded.value)", (update_id + 1,))

    def button(self, uid, router, action, target='', grant_epoch=''):
        token = secrets.token_urlsafe(18)
        with self.connect() as db:
            now = int(time.time())
            db.execute('DELETE FROM buttons WHERE expires < ?', (now,))
            db.execute('INSERT INTO buttons(token,uid,router,action,target,expires,grant_epoch) VALUES (?,?,?,?,?,?,?)',
                       (token, uid, router, action, target, now + (120 if action in ('admin_confirm', 'admin_reboot_confirm', 'update_install') else 900), grant_epoch))
        return token

    def take_button(self, token, uid):
        if not isinstance(token, str) or len(token) > 40:
            raise SafeError('Кнопка недействительна. Откройте /start.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM buttons WHERE token=? AND uid=? AND expires>=? AND used=0',
                             (token, uid, int(time.time()))).fetchone()
            if row is None:
                raise SafeError('Кнопка устарела или уже использована. Откройте /start.')
            db.execute('UPDATE buttons SET used=1 WHERE token=?', (token,))
            return dict(row)

    def begin(self, update_id, uid, router, action, target):
        with self.connect() as db:
            result = db.execute('INSERT OR IGNORE INTO operations VALUES (?,?,?,?,?,?,NULL,?)',
                                (update_id, uid, router, action, target, 'running', int(time.time())))
            return result.rowcount == 1

    def begin_admin(self, update_id, uid, router, action):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            now = int(time.time())
            if db.execute("SELECT 1 FROM operations WHERE router=? AND action IN ('netbird','proxy','reboot','update_app','update_xray','update_netbird') AND created>?", (router, now - 300)).fetchone():
                raise SafeError('После административной операции подождите 5 минут.')
            result = db.execute('INSERT OR IGNORE INTO operations VALUES (?,?,?,?,?,?,NULL,?)',
                                (update_id, uid, router, action, '', 'running', now))
            return result.rowcount == 1

    def cancel_admin(self, uid, rid):
        with self.connect() as db:
            db.execute("DELETE FROM buttons WHERE uid=? AND router=? AND action IN ('admin_confirm','admin_reboot_confirm','update_install')", (uid, rid))

    def finish(self, update_id, state, job=None):
        with self.connect() as db:
            db.execute('UPDATE operations SET state=?,job=coalesce(?,job) WHERE update_id=?',
                       (state, job, update_id))


    def presence_result(self, rid, reachable, checked, transport=None):
        with self.connect() as db:
            db.execute('INSERT INTO router_presence(router,reachable,checked,last_seen,transport) VALUES (?,?,?,?,?) '
                       'ON CONFLICT(router) DO UPDATE SET reachable=excluded.reachable,checked=excluded.checked,'
                       'last_seen=CASE WHEN excluded.reachable THEN max(coalesce(router_presence.last_seen,0),excluded.checked) ELSE router_presence.last_seen END,'
                       'transport=excluded.transport WHERE excluded.checked>=router_presence.checked',
                       (rid, int(reachable), checked, checked if reachable else None, transport))

    def presence_record(self, rid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM router_presence WHERE router=?', (rid,)).fetchone()
            return dict(row) if row else None

    def presence(self):
        with self.connect() as db:
            return {r['router']: dict(r) for r in db.execute('SELECT * FROM router_presence')}

    def router_name(self, rid, fallback):
        with self.connect() as db:
            row = db.execute('SELECT name FROM router_names WHERE router=?', (rid,)).fetchone()
            return row['name'] if row else fallback

    def router_names(self):
        with self.connect() as db:
            return dict(db.execute('SELECT router,name FROM router_names'))

    def rename_router(self, actor, rid, name):
        if (not isinstance(name, str) or not 1 <= len(name) <= 80 or
                not name.strip() or any(not c.isprintable() for c in name)):
            raise SafeError('Имя: от 1 до 80 символов, без переводов строк.')
        with self.connect() as db:
            db.execute('INSERT INTO router_names(router,name) VALUES (?,?) '
                       'ON CONFLICT(router) DO UPDATE SET name=excluded.name', (rid, name.strip()))
            db.execute('INSERT INTO access_audit(actor,uid,router,action,created) VALUES (?,?,?,?,?)',
                       (actor, actor, rid, 'rename', int(time.time())))

    def router_code(self, rid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM router_ids WHERE router=?', (rid,)).fetchone():
                db.execute('INSERT INTO router_ids(router) VALUES (?)', (rid,))
            seq = db.execute('SELECT seq FROM router_ids WHERE router=?', (rid,)).fetchone()[0]
            return f'R-{seq:06d}'

    def resolve_user(self, text):
        if re.fullmatch(r'U-[0-9]{6,}', text):
            with self.connect() as db:
                row = db.execute('SELECT uid FROM user_ids WHERE seq=?', (int(text[2:]),)).fetchone()
                if row:
                    return str(row[0])
            raise SafeError('Пользователь с таким ID не найден.')
        return text

    def user_info(self, uid, name=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM user_ids WHERE uid=?', (uid,)).fetchone():
                db.execute('INSERT INTO user_ids(uid) VALUES (?)', (uid,))
            if name is not None:
                clean = ''.join(c for c in name if c.isprintable())[:100]
                db.execute('UPDATE user_ids SET name=? WHERE uid=?', (clean, uid))
            row = db.execute('SELECT seq,name FROM user_ids WHERE uid=?', (uid,)).fetchone()
            return f'U-{row[0]:06d}', row[1]

    def pending_notifications(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM notifications WHERE state='pending' AND retry_at<=? ORDER BY id LIMIT 5", (int(time.time()),))]

    def notification_state(self, event_id, state, retry_at=0):
        with self.connect() as db:
            db.execute('UPDATE notifications SET state=?,retry_at=? WHERE id=?', (state, retry_at, event_id))

    def monitor_status(self, rid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM monitoring WHERE router=?', (rid,)).fetchone()
            return dict(row) if row else {'enabled': 0, 'failures': 0, 'offline': 0, 'checked': None, 'proxy_failures': 0, 'last_health': 0, 'proxy_bad': 0}

    def monitor_enable(self, rid, enabled):
        with self.connect() as db:
            db.execute('INSERT INTO monitoring(router,enabled) VALUES (?,?) ON CONFLICT(router) DO UPDATE SET enabled=excluded.enabled,failures=0,offline=0,checked=NULL,proxy_failures=0,last_health=0,proxy_bad=0', (rid, int(enabled)))
            db.execute("UPDATE monitor_events SET state='superseded' WHERE router=? AND state='pending'", (rid,))

    def monitor_result(self, rid, reachable, health=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM monitoring WHERE router=? AND enabled=1', (rid,)).fetchone()
            if not row:
                return
            failures = 0 if reachable else row['failures'] + 1
            offline = int(failures >= 3) if not reachable else 0
            if offline != row['offline']:
                db.execute('INSERT INTO monitor_events(router,offline) VALUES (?,?)', (rid, offline))
            db.execute('UPDATE monitoring SET failures=?,offline=?,checked=? WHERE router=?', (failures, offline, int(time.time()), rid))
            checked = (health or {}).get('health_checked')
            ok = (health or {}).get('proxy_ok')
            if (reachable and type(checked) in (int, float) and
                    time.time()-180 <= checked <= time.time()+30 and checked > row['last_health'] and type(ok) is bool):
                failed = 0 if ok else row['proxy_failures'] + 1
                bad = int(failed >= 3) if not ok else 0
                if bad != row['proxy_bad']:
                    db.execute("INSERT INTO monitor_events(router,offline,kind) VALUES (?,?,'proxy')", (rid, bad))
                db.execute('UPDATE monitoring SET proxy_failures=?,proxy_bad=?,last_health=? WHERE router=?', (failed, bad, checked, rid))

    def pending_monitor_events(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM monitor_events WHERE state='pending' ORDER BY id LIMIT 5")]

    def finish_monitor_event(self, event_id):
        with self.connect() as db:
            db.execute("UPDATE monitor_events SET state='delivered' WHERE id=?", (event_id,))

    def cache_hwid(self, rid, value):
        if value is not None and (not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9=-]{10,64}',value)):
            value=None
        with self.connect() as db:
            db.execute('INSERT INTO router_hwids VALUES (?,?,?) ON CONFLICT(router) DO UPDATE SET hwid=excluded.hwid,updated=excluded.updated', (rid,value,int(time.time())))

    def hwid(self, rid):
        with self.connect() as db:
            row=db.execute('SELECT hwid FROM router_hwids WHERE router=?',(rid,)).fetchone()
            return row[0] if row else None

    def operator_dialog(self, uid, stage=None, name=''):
        with self.connect() as db:
            if stage=='clear':db.execute('DELETE FROM operator_dialogs WHERE uid=?',(uid,));return
            if stage:
                db.execute('INSERT INTO operator_dialogs VALUES (?,?,?,?) ON CONFLICT(uid) DO UPDATE SET stage=excluded.stage,name=excluded.name,expires=excluded.expires',(uid,stage,name,int(time.time())+900))
            row=db.execute('SELECT * FROM operator_dialogs WHERE uid=? AND expires>=?',(uid,int(time.time()))).fetchone()
            return dict(row) if row else None

    def operator_start(self, uid, action):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM operator_jobs WHERE state='pending'").fetchone():
                raise SafeError('Административная операция уже выполняется. Дождитесь результата.')
            if db.execute("SELECT 1 FROM operations WHERE state='running'").fetchone():
                raise SafeError('Выполняется операция роутера. Дождитесь её завершения.')
            if db.execute('SELECT 1 FROM operator_jobs WHERE action=? AND created>?',(action,int(time.time())-60)).fetchone():
                raise SafeError('Подождите минуту перед повтором операции.')
            job=str(uuid.uuid4())
            db.execute("INSERT INTO operator_jobs(id,uid,action,created,state) VALUES (?,?,?,?,'pending')",(job,uid,action,int(time.time())))
            return job

    def operator_pending(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM operator_jobs WHERE state='pending'")]

    def operator_finish(self, job, state):
        with self.connect() as db:db.execute('UPDATE operator_jobs SET state=? WHERE id=?',(state,job))

    def cache_subscription(self, rid, data):
        sid = data.get('id')
        if sid is not None and not re.fullmatch(r'[0-9]{1,12}', str(sid)):
            sid = None
        with self.connect() as db:
            db.execute('INSERT INTO router_subscriptions VALUES (?,?,?) ON CONFLICT(router) DO UPDATE SET subscription_id=excluded.subscription_id,updated=excluded.updated',
                       (rid, sid, int(time.time())))

    def customer_numbers(self, uid):
        with self.connect() as db:
            return [row[0] for row in db.execute('SELECT DISTINCT s.subscription_id FROM router_subscriptions s JOIN grants g ON g.router=s.router WHERE g.uid=? AND s.subscription_id IS NOT NULL ORDER BY s.subscription_id', (uid,))]

    def set_dialog(self, uid, rid):
        with self.connect() as db:
            db.execute('INSERT INTO input_dialogs VALUES (?,?,?) ON CONFLICT(uid) DO UPDATE SET router=excluded.router,expires=excluded.expires',
                       (uid, rid, int(time.time()) + 600))

    def dialog(self, uid):
        with self.connect() as db:
            db.execute('DELETE FROM input_dialogs WHERE expires < ?', (int(time.time()),))
            row = db.execute('SELECT router FROM input_dialogs WHERE uid=?', (uid,)).fetchone()
            return row[0] if row else None

    def clear_dialog(self, uid):
        with self.connect() as db:
            db.execute('DELETE FROM input_dialogs WHERE uid=?', (uid,))

    def cancel_confirmations(self, uid, rid):
        with self.connect() as db:
            db.execute("DELETE FROM buttons WHERE uid=? AND router=? AND action IN ('grant','revoke')", (uid, rid))

    def grant_epoch(self, uid, rid):
        with self.connect() as db:
            row = db.execute('SELECT epoch FROM grants WHERE uid=? AND router=?', (uid, rid)).fetchone()
            return row[0] if row else None

    def visible_routers(self, uid):
        with self.connect() as db:
            return {row[0] for row in db.execute('SELECT router FROM grants WHERE uid=?', (uid,))}

    def clients(self, rid):
        with self.connect() as db:
            return [row[0] for row in db.execute('SELECT uid FROM grants WHERE router=? ORDER BY uid', (rid,))]

    def change_access(self, actor, uid, rid, grant):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if grant:
                changed = db.execute('INSERT OR IGNORE INTO grants VALUES (?,?,?,?)',
                                     (uid, rid, secrets.token_urlsafe(16), int(time.time()))).rowcount
            else:
                changed = db.execute('DELETE FROM grants WHERE uid=? AND router=?', (uid, rid)).rowcount
                db.execute('DELETE FROM buttons WHERE uid=? AND router=?', (uid, rid))
            db.execute('INSERT INTO access_audit(actor,uid,router,action,created) VALUES (?,?,?,?,?)',
                       (actor, uid, rid, 'grant' if grant else 'revoke', int(time.time())))
            if changed:
                row = db.execute('SELECT epoch FROM grants WHERE uid=? AND router=?', (uid, rid)).fetchone()
                db.execute('INSERT INTO notifications(uid,router,granted,epoch) VALUES (?,?,?,?)',
                           (uid, rid, int(grant), row[0] if row else None))
            return bool(changed)


def ssh_command(config, router, command):
    return ['ssh', '-T', '-F', '/dev/null',
            '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'PreferredAuthentications=publickey',
            '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
            '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + config['known_hosts'],
            '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
            '-o', 'ClearAllForwardings=yes',
            '-i', config['ssh_key'], '-p', str(router['port']),
            'root@' + router['host'], command]


class TransportError(SafeError):
    """Transport failed; mutations must never be replayed automatically."""


class Bridge:
    def __init__(self, config):
        self.config = config

    def call(self, router, command, transport=None):
        allowed = command in ('xtlsbot-v1 status', 'xtlsbot-v1 locations', 'xtlsbot-v1 diagnostics', 'xtlsbot-v1 auto', 'xtlsbot-v1 admin-status', 'xtlsbot-v1 admin-open-rescue', 'xtlsbot-v1 updates')
        allowed |= bool(re.fullmatch(r'xtlsbot-v1 select cfg[A-Za-z0-9_-]{6}', command))
        allowed |= bool(re.fullmatch(r'xtlsbot-v1 job [a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', command))
        allowed |= bool(re.fullmatch(r'xtlsbot-v1 admin (netbird|proxy|reboot) [a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', command))
        allowed |= bool(re.fullmatch(r'xtlsbot-v1 update-check (app|xray|netbird) [a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', command))
        allowed |= bool(re.fullmatch(r'xtlsbot-v1 update-install (app|xray|netbird) [a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12} [a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', command))
        if not allowed:
            raise SafeError('Недопустимая операция.')
        readonly = command in ('xtlsbot-v1 status', 'xtlsbot-v1 locations', 'xtlsbot-v1 diagnostics', 'xtlsbot-v1 admin-status', 'xtlsbot-v1 updates') or command.startswith('xtlsbot-v1 job ')
        endpoints = [('netbird', router)]
        if router.get('rescue'):
            endpoints.append(('rescue', router['rescue']))
        if command.startswith(('xtlsbot-v1 admin ', 'xtlsbot-v1 update-install ')):
            transport = 'rescue'
        if transport is not None:
            if transport not in ('netbird', 'rescue'):
                raise SafeError('Недопустимый канал управления.')
            endpoints = [pair for pair in endpoints if pair[0] == transport]
            if not endpoints:
                raise SafeError('Аварийный SSH не настроен.')
        for index, (transport, endpoint) in enumerate(endpoints):
            try:
                # Probe before a mutation, then dispatch it exactly once. An SSH
                # failure after dispatch may mean the operation was accepted.
                if not readonly and len(endpoints) > 1:
                    self._call_once(endpoint, 'xtlsbot-v1 status')
                elif readonly:
                    data = self._call_once(endpoint, command)
                    return {**data, '_transport': transport}
            except TransportError:
                if index + 1 < len(endpoints):
                    continue
                raise TransportError('Роутер недоступен по настроенным каналам.') from None
            try:
                data = self._call_once(endpoint, command)
            except TransportError:
                raise SafeError('Ответ на операцию потерян. Выполнение не подтверждено; команда повторно не отправлена. Проверьте статус роутера.') from None
            return {**data, '_transport': transport}

    def _call_once(self, router, command):
        try:
            result = subprocess.run(ssh_command(self.config, router, command),
                                    capture_output=True, timeout=23)
            # Never send raw SSH stderr, config or router response to Telegram.
            if len(result.stdout) > 262144:
                raise SafeError('Некорректный ответ роутера.')
            if result.returncode == 255:
                raise TransportError('Нет ответа от роутера по SSH.')
            reply = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            raise TransportError('Нет ответа от роутера по SSH.') from None
        except ValueError:
            raise SafeError('Некорректный ответ роутера.') from None
        if not isinstance(reply, dict) or reply.get('schema') != 1:
            raise SafeError('Версия обработчика роутера не поддерживается.')
        if result.returncode or reply.get('ok') is not True:
            error = reply.get('error')
            code = error.get('code') if isinstance(error, dict) else None
            messages = {
                'busy': 'На роутере уже выполняется операция. Повторите позже.',
                'cooldown': 'После административной операции подождите 5 минут.',
                'netbird_autostart_required': 'Для операции требуется автозапуск NetBird.',
                'rescue_required': 'Для перезагрузки требуется включённый аварийный доступ.',
                'proxy_autostart_required': 'Для перезагрузки требуется автозапуск прокси.',
                'proxy_disabled': 'Прокси отключён в настройках роутера.',
                'updates_unavailable': 'Обновите обработчик обновлений на роутере.',
                'plan_expired': 'План установки устарел. Проверьте версии заново.',
                'installed_changed': 'Установленная версия изменилась. Проверьте версии заново.',
                'admin_unavailable': 'Обновите административный обработчик на роутере.',
                'unknown_location': 'Список локаций изменился. Откройте его заново.',
                'job_replaced': 'Задание заменено другой операцией. Проверьте статус.',
                'proxy_not_running': 'Прокси на роутере остановлен.',
            }
            raise SafeError(messages.get(code, 'Роутер отклонил операцию.'))
        if not isinstance(reply.get('data'), dict):
            raise SafeError('Некорректный ответ роутера.')
        return reply['data']


def load_config(path):
    config = json.loads(Path(path).read_text())
    if type(config.get('admin_id')) is not int or config['admin_id'] <= 0:
        raise ValueError('admin_id')
    if config.get('bot_username') != 'xtlsproroutbot':
        raise ValueError('bot_username')
    for key in ('ssh_key', 'known_hosts', 'database'):
        if not Path(config[key]).is_absolute():
            raise ValueError('absolute path required')
    if not config.get('routers'):
        raise ValueError('routers')
    rescue_ports = set()
    device_ids = set()
    for rid, router in config['routers'].items():
        if not re.fullmatch(r'[a-z0-9_-]{1,32}', rid):
            raise ValueError('router id')
        if 'device_id' in router:
            device = router['device_id']
            if not isinstance(device, str) or not JOB.fullmatch(device) or device in device_ids:
                raise ValueError('duplicate or invalid device id')
            device_ids.add(device)
        ipaddress.ip_address(router['host'])
        if type(router.get('port')) is not int or not 1 <= router['port'] <= 65535:
            raise ValueError('router port')
        if 'rescue' in router:
            rescue = router['rescue']
            if not isinstance(rescue, dict) or set(rescue) != {'host', 'port'}:
                raise ValueError('rescue endpoint')
            if rescue['host'] != '127.0.0.1' or type(rescue['port']) is not int or not 1024 <= rescue['port'] <= 65535:
                raise ValueError('rescue loopback port')
            if rescue['port'] in rescue_ports:
                raise ValueError('duplicate rescue port')
            rescue_ports.add(rescue['port'])
    if type(config.get('rich_messages', True)) is not bool:
        raise ValueError('rich_messages')
    config.setdefault('rich_messages', True)
    return config


class Bot:
    def __init__(self, config, telegram, store, bridge):
        self.config, self.tg, self.store, self.bridge = config, telegram, store, bridge
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.locks = {rid: threading.Lock() for rid in config['routers']}
        self.policy_lock = threading.RLock()
        self.read_guard = threading.Lock()
        self.read_busy = set()
        for rid in sorted(config['routers']):
            self.store.router_code(rid)

    @staticmethod
    def support_button():
        return {'text': '💬 Техподдержка', 'url': SUPPORT_URL}

    def router_name(self, rid):
        return self.store.router_name(rid, self.config['routers'][rid]['name'])

    def router_label(self, rid):
        hwid=self.store.hwid(rid)
        return self.router_name(rid) + (' · HWID ' + hwid if hwid else ' · HWID не получен')

    def user_label(self, uid):
        code, name = self.store.user_info(uid)
        numbers = self.store.customer_numbers(uid)
        label = 'Клиент ' + ' / '.join('№' + str(n) for n in numbers) if numbers else 'Пользователь'
        return label + (' · ' + name if name else '') + ' · Telegram ID ' + str(uid)

    def identity(self, uid):
        numbers = self.store.customer_numbers(uid)
        label = 'Клиент ' + ' / '.join('№' + str(n) for n in numbers) + '\n' if numbers else ''
        return label + 'Telegram ID: ' + str(uid)

    def submit_read(self, uid, rid, action, epoch, target=''):
        with self.read_guard:
            if uid in self.read_busy:
                return
            self.read_busy.add(uid)
        def work():
            try:
                {'status': self.status, 'locations': self.locations, 'diagnostics': self.diagnostics, 'updates': self.updates_menu, 'update_prompt': lambda u, r, e: self.update_prompt(u, r, target)}[action](uid, rid, epoch)
            except SafeError as error:
                self.inform(uid, str(error))
            except Exception:
                LOG.error('read request failed')
                self.inform(uid, 'Не удалось получить состояние роутера.')
            finally:
                with self.read_guard:
                    self.read_busy.discard(uid)
        try:
            self.pool.submit(work)
        except Exception:
            with self.read_guard:
                self.read_busy.discard(uid)
            raise

    def monitor_check(self, rid):
        # One background read also feeds optional alerts. Never issue a mutation.
        if self.locks[rid].locked():
            return
        checked = time.time()
        previous = self.store.presence_record(rid)
        if previous and 0 <= checked - previous['checked'] < 60:
            return
        try:
            data = self.bridge.call(self.config['routers'][rid], 'xtlsbot-v1 status')
            reachable = True
        except SafeError:
            reachable = False
            data = None
        self.store.presence_result(rid, reachable, checked, (data or {}).get('_transport'))
        self.store.monitor_result(rid, reachable, data)

    def monitor_loop(self):
        # Independent of interactive jobs; at most two SSH reads in flight.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as checks:
            while True:
                routers = list(self.config['routers'])
                for start in range(0, len(routers), 2):
                    jobs = [checks.submit(self.monitor_check, rid) for rid in routers[start:start+2]]
                    for job in jobs:
                        try:
                            job.result()
                        except Exception:
                            LOG.error('monitor check failed')
                time.sleep(30)

    @staticmethod
    def presence_view(record, now=None):
        now = time.time() if now is None else now
        if not record or not 0 <= now - record['checked'] <= 180:
            return 'unknown', '⚪ Нет свежих данных'
        return ('online', '🟢 В сети') if record['reachable'] else ('offline', '🔴 Нет связи')

    @staticmethod
    def moscow_stamp(value):
        if not value:
            return 'ещё не проверялся'
        return datetime.fromtimestamp(value, timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')

    def monitor_menu(self, uid, rid):
        self.admin(uid)
        state = self.store.monitor_status(rid)
        text = (self.router_label(rid) + ' · Мониторинг\n' +
                ('Включён' if state['enabled'] else 'Выключен') +
                '\nФоновые проверки через NetBird и доступный аварийный SSH.'
                '\nУведомление после трёх ошибок SSH или трёх разных свежих ошибок HTTPS, и при восстановлении.'
                '\nПроверки не перезапускают службы и не меняют настройки.')
        self.send(uid, text, [[self.button(uid, rid, 'Выключить' if state['enabled'] else 'Включить',
                         'monitor_off' if state['enabled'] else 'monitor_on')],
                         [self.button(uid, rid, '← Статус', 'status')]])

    def deliver_notifications(self):
        for event in self.store.pending_monitor_events():
            if event['router'] not in self.config['routers']:
                self.store.finish_monitor_event(event['id'])
                continue
            if event['kind'] == 'proxy':
                text = ('⚠️ Прокси не проходит HTTPS-проверку: ' if event['offline'] else '✅ HTTPS-проверка прокси восстановлена: ')
            else:
                text = ('⚠️ Нет ответа по SSH через NetBird: ' if event['offline'] else '✅ SSH-доступ восстановлен: ')
            text += self.router_label(event['router'])
            self.send(self.config['admin_id'], text)
            self.store.finish_monitor_event(event['id'])
        for event in self.store.pending_notifications():
            uid, rid = event['uid'], event['router']
            if rid not in self.config['routers']:
                self.store.notification_state(event['id'], 'superseded')
                continue
            with self.policy_lock:
                current = self.store.grant_epoch(uid, rid)
                if (event['granted'] and current != event['epoch']) or (not event['granted'] and current is not None):
                    self.store.notification_state(event['id'], 'superseded')
                    continue
                payload = {'chat_id': uid}
                if event['granted']:
                    payload['text'] = '✅ Доступ выдан: ' + self.router_label(rid)
                    payload['reply_markup'] = {'inline_keyboard': [[self.button(uid, rid, 'Открыть роутер', 'status')]]}
                else:
                    payload['text'] = 'Доступ отозван: ' + self.router_label(rid)
                    remaining = sorted(self.visible(uid))
                    if remaining:
                        payload['reply_markup'] = {'inline_keyboard': [[self.button(uid, remaining[0], 'Мои роутеры', 'menu')]]}
                try:
                    self.tg.call('sendMessage', **payload)
                    self.store.notification_state(event['id'], 'delivered')
                except SafeError as error:
                    if error.code in (400, 403):
                        self.store.notification_state(event['id'], 'blocked')
                        self.send(self.config['admin_id'], 'Уведомление не доставлено: ' + self.user_label(uid) +
                                  '. Клиент должен открыть бот или снять блокировку. Привязка сохранена.')
                    else:
                        self.store.notification_state(event['id'], 'pending', int(time.time()) + 30)

    def admin(self, uid):
        if type(uid) is not int or uid != self.config['admin_id']:
            raise SafeError('Только для администратора.')

    def visible(self, uid):
        if type(uid) is not int or not 0 < uid < 2**52:
            return set()
        if uid == self.config['admin_id']:
            return set(self.config['routers'])
        return self.store.visible_routers(uid) & self.config['routers'].keys()

    def authorize(self, uid, router=None, epoch=None):
        if not self.visible(uid):
            raise SafeError('Доступ запрещён.')
        if router is not None and router not in self.visible(uid):
            raise SafeError('Роутер недоступен.')
        if router is not None and uid != self.config['admin_id']:
            current = self.store.grant_epoch(uid, router)
            if epoch is not None and current != epoch:
                raise SafeError('Доступ изменился. Откройте /start.')

    def router_call(self, uid, rid, command, epoch=None, transport=None):
        # Serialize revocation with authorization and SSH dispatch. A command
        # already accepted by the router may finish; no subsequent dispatch occurs.
        with self.policy_lock:
            self.authorize(uid, rid, epoch)
            if command.startswith(('xtlsbot-v1 admin', 'xtlsbot-v1 update')):
                self.admin(uid)
            checked = time.time()
            try:
                if transport is None:
                    result = self.bridge.call(self.config['routers'][rid], command)
                else:
                    result = self.bridge.call(self.config['routers'][rid], command, transport=transport)
            except TransportError:
                if command == 'xtlsbot-v1 status':
                    self.store.presence_result(rid, False, checked)
                raise
            if command == 'xtlsbot-v1 status':
                self.store.presence_result(rid, True, checked, result.get('_transport'))
            self.authorize(uid, rid, epoch)
            return result

    def send_router(self, uid, rid, text, keyboard=None, epoch=None, rich=None):
        with self.policy_lock:
            self.authorize(uid, rid, epoch)
            self.send(uid, text, keyboard, rich=rich)

    def inform(self, uid, text, keyboard=None):
        # Public private-chat response: own ID/help only, never router data.
        args = {'chat_id': uid, 'text': text[:4000]}
        if keyboard is not None:
            args['reply_markup'] = {'inline_keyboard': keyboard}
        self.tg.call('sendMessage', **args)

    def send(self, uid, text, keyboard=None, rich=None):
        self.authorize(uid)
        args = {'chat_id': uid, 'text': text[:4000]}
        if keyboard is not None:
            args['reply_markup'] = {'inline_keyboard': keyboard}
        if rich is None and keyboard:
            rich = [{'type': 'paragraph', 'text': text[:4000]}]
        if rich and self.config.get('rich_messages', False):
            try:
                payload = {'chat_id': uid}
                buttons = [{'type': 'buttons', 'buttons': row} for row in (keyboard or []) if row]
                self.tg.call('sendRichMessage', rich_message={'blocks': rich + buttons, 'skip_entity_detection': True}, **payload)
                return
            except SafeError as error:
                # Only explicit API rejection permits a plain-text fallback.
                # A timeout may mean the rich message arrived: never duplicate it.
                if error.code not in (400, 404):
                    raise
        self.tg.call('sendMessage', **args)

    def button(self, uid, rid, text, action, target=''):
        self.authorize(uid, rid)
        epoch = '' if uid == self.config['admin_id'] else self.store.grant_epoch(uid, rid)
        return {'text': text, 'callback_data': self.store.button(uid, rid, action, target, epoch)}

    @staticmethod
    def search_key(value):
        return re.sub(r'[\s\-№#]', '', str(value).casefold())

    def menu(self, uid, query=None, page=None):
        visible = self.visible(uid)
        if not visible:
            raise SafeError('Доступ к роутерам не выдан.')
        previous = self.store.catalog(uid)
        query = previous['query'] if query is None else query
        page = previous['page'] if page is None else page
        if not isinstance(query, str) or len(query) > 100 or any(ord(c) < 32 for c in query):
            raise SafeError('Поиск: от 1 до 100 символов, без переводов строк.')
        if type(page) is not int or page < 0:
            raise SafeError('Некорректная страница каталога.')
        hwids, numbers = self.store.catalog_metadata()
        needle = self.search_key(query)
        aliases = self.store.router_names()
        names = {rid: aliases.get(rid, self.config['routers'][rid]['name']) for rid in visible}
        presence = self.store.presence()
        states = {rid: self.presence_view(presence.get(rid)) for rid in visible}
        ordered = sorted(visible, key=lambda r: (names[r].casefold(), r))
        found = [rid for rid in ordered if not needle or any(needle in self.search_key(value)
                 for value in (names[rid], hwids.get(rid, ''), numbers.get(rid, '')))]
        pages = max(1, (len(found) + 9) // 10)
        page = min(page, pages - 1)
        self.store.catalog(uid, query, page)
        first = ordered[0]
        counts = {}
        for rid in ordered:
            name = names[rid].casefold()
            counts[name] = counts.get(name, 0) + 1
        rows = []
        for rid in found[page * 10:(page + 1) * 10]:
            name = names[rid]
            if counts[name.casefold()] > 1:
                # Real HWID distinguishes repeated names; never invent a hardware ID.
                suffix = hwids.get(rid) or numbers.get(rid) or rid
                name = name[:40] + ' · ' + suffix
            icon = states[rid][1].split(' ')[0]
            rows.append([self.button(uid, rid, icon + ' ' + name[:77], 'status')])
        nav = []
        if page:
            nav.append(self.button(uid, first, '⬅️ Назад', 'catalog_page', json.dumps([query, page - 1])))
        if page + 1 < pages:
            nav.append(self.button(uid, first, 'Вперёд ➡️', 'catalog_page', json.dumps([query, page + 1])))
        if nav:
            rows.append(nav)
        rows.append([self.button(uid, first, '🔎 Поиск', 'catalog_search'),
                     self.button(uid, first, '📋 Все роутеры', 'catalog_all')])
        if uid != self.config['admin_id']:
            rows.append([self.support_button()])
        rows.append([self.button(uid, first, '🆔 Мой ID', 'whoami'),
                     self.button(uid, first, 'ℹ️ Помощь', 'help')])
        if uid == self.config['admin_id']:
            rows.append([self.button(uid, first, '⚙️ Администрирование бота', 'operator_menu')])
        text = 'xtlsproVPN · Мои роутеры'
        if query:
            text += '\nПоиск: ' + query
        text += f'\nНайдено: {len(found)} · Страница {page + 1}/{pages}'
        totals = {state: sum(states[rid][0] == state for rid in found) for state in ('online', 'offline', 'unknown')}
        text += f"\n🟢 В сети: {totals['online']} · 🔴 Нет связи: {totals['offline']} · ⚪ Нет данных: {totals['unknown']}"
        text += '\nВыберите роутер:' if found else '\nНичего не найдено. Попробуйте другое имя, HWID или номер подписки.'
        rich = [{'type': 'heading', 'size': 3, 'text': 'Мои роутеры'},
                {'type': 'paragraph', 'text': f"🟢 {totals['online']} в сети · 🔴 {totals['offline']} нет связи · ⚪ {totals['unknown']} нет данных"}]
        if query:
            rich.append({'type': 'paragraph', 'text': 'Поиск: ' + query})
        rich += [{'type': 'paragraph', 'text': f'Найдено: {len(found)} · Страница {page + 1}/{pages}'},
                 {'type': 'footer', 'text': 'Статусы по последней проверке; данные старше 3 минут показаны серым.'}]
        self.send(uid, text, rows, rich=rich)

    def status(self, uid, rid, epoch=None):
        self.authorize(uid, rid)
        router = self.config['routers'][rid]
        try:
            data = self.router_call(uid, rid, 'xtlsbot-v1 status', epoch)
        except TransportError:
            self.offline_status(uid, rid, epoch)
            return
        try:
            locations = self.router_call(uid, rid, 'xtlsbot-v1 locations', epoch)
        except SafeError:
            locations = {}
        if 'hwid' in data:
            self.store.cache_hwid(rid,data['hwid'])
        if isinstance(data.get('subscription'), dict):
            self.store.cache_subscription(rid, data['subscription'])
        names = [str(n.get('name', 'Локация'))[:120] for n in locations.get('nodes', [])
                 if n.get('id') in data.get('selected', [])]
        mode = 'Автовыбор' if data.get('mode') == 'auto' else 'Ручной'
        running = 'работает' if data.get('running') else 'остановлен'
        # Cached health is explicitly labelled; selection success isn't a new probe.
        health = {True: 'успешна', False: 'ошибка', None: 'нет данных'}.get(data.get('proxy_ok'), 'нет данных')
        text = (f"{self.router_label(rid)}\nПрокси: {running}\nРежим: {mode}\n"
                f"Локация: {', '.join(names) or 'нет данных'}\n"
                f"Последняя проверка прокси: {health}\nВерсия: {str(data.get('version') or 'нет данных')[:40]}" +
                '\n\n' + self.subscription_text(data.get('subscription')))
        checked = self.store.presence_record(rid) or {}
        text += '\nДоступность: 🟢 В сети\nПроверено: ' + self.moscow_stamp(checked.get('checked'))
        if uid == self.config['admin_id'] and data.get('_transport'):
            text += '\nКанал управления: ' + ('аварийный SSH' if data['_transport'] == 'rescue' else 'NetBird')
        rows = [[self.button(uid, rid, '🌍 Локации', 'locations'),
                 self.button(uid, rid, '🔄 Статус', 'status')],
                [self.button(uid, rid, '⚡ Автовыбор', 'auto'),
                 self.button(uid, rid, '🩺 Диагностика', 'diagnostics')]]
        if uid == self.config['admin_id']:
            rows.append([self.button(uid, rid, '🛠 Восстановление', 'admin_menu'),
                         self.button(uid, rid, '📦 Обновления', 'updates')])
            rows.append([self.button(uid, rid, '👥 Доступ клиентов', 'access'),
                         self.button(uid, rid, '🔔 Мониторинг', 'monitor')])
        if uid != self.config['admin_id']:
            rows.append([self.support_button()])
        rows.append([self.button(uid, rid, '🏠 Мои роутеры', 'menu')])
        rich = [{'type': 'heading', 'size': 3, 'text': self.router_name(rid)},
                {'type': 'paragraph', 'text': '🟢 В сети · Прокси ' + running},
                {'type': 'blockquote', 'blocks': [{'type': 'paragraph', 'text':
                    f"Режим: {mode}\nЛокация: {', '.join(names) or 'нет данных'}\nПроверка прокси: {health}\nВерсия: {str(data.get('version') or 'нет данных')[:40]}"}]},
                {'type': 'heading', 'size': 4, 'text': '🧾 Подписка'},
                {'type': 'blockquote', 'blocks': [{'type': 'paragraph', 'text': self.subscription_text(data.get('subscription'))}]}]
        details = 'HWID: ' + str(self.store.hwid(rid) or 'нет данных')
        if uid == self.config['admin_id'] and data.get('_transport'):
            details += '\nКанал управления: ' + ('аварийный SSH' if data['_transport'] == 'rescue' else 'NetBird')
        rich += [{'type': 'details', 'summary': 'Сведения об устройстве', 'blocks': [{'type': 'paragraph', 'text': details}]},
                 {'type': 'footer', 'text': 'Проверено: ' + self.moscow_stamp(checked.get('checked'))}]
        self.send_router(uid, rid, text, rows, epoch, rich=rich)

    def offline_status(self, uid, rid, epoch=None):
        self.authorize(uid, rid, epoch)
        state = self.store.presence_record(rid) or {}
        text = self.router_label(rid) + '\n🔴 Нет связи\nСостояние прокси: нет свежих данных.'
        text += '\nПроверено: ' + self.moscow_stamp(state.get('checked'))
        text += '\nПоследний успешный ответ: ' + self.moscow_stamp(state.get('last_seen'))
        rows = [[self.button(uid, rid, '🔄 Статус', 'status'), self.button(uid, rid, '🏠 Мои роутеры', 'menu')]]
        if uid != self.config['admin_id']:
            rows.append([self.support_button()])
        rich = [{'type': 'heading', 'size': 3, 'text': self.router_name(rid)},
                {'type': 'paragraph', 'text': '🔴 Нет связи'},
                {'type': 'blockquote', 'blocks': [{'type': 'paragraph', 'text': 'Состояние прокси неизвестно: роутер не ответил.'}]},
                {'type': 'footer', 'text': 'Последний успешный ответ: ' + self.moscow_stamp(state.get('last_seen'))},
                {'type': 'footer', 'text': 'Проверено: ' + self.moscow_stamp(state.get('checked'))}]
        self.send_router(uid, rid, text, rows, epoch, rich=rich)

    @staticmethod
    def subscription_text(data):
        if not isinstance(data, dict):
            return 'Карточка подписки: требуется обновить SSH-обработчик роутера.'
        if not data.get('available'):
            return 'Подписка: нет сохранённых данных.'
        sid = str(data.get('id', ''))
        title = 'Подписка xtlsproVPN' + (' · №' + sid if re.fullmatch(r'[0-9]{1,12}', sid) else '')
        def stamp(value):
            try:
                if type(value) not in (int, float) or value <= 0:
                    return 'нет данных'
                return datetime.fromtimestamp(value, timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')
            except (ValueError, OverflowError, OSError):
                return 'нет данных'
        def volume(value):
            return f'{value / 1024**3:.1f} ГиБ' if type(value) in (int, float) and 0 <= value < 2**53 else 'нет данных'
        expire = data.get('expire')
        until = stamp(expire)
        if type(expire) in (int, float) and expire > 0:
            until += ' · ' + (str(math.ceil((expire-time.time())/86400)) + ' дн.' if expire > time.time() else 'истекла')
        total = 'безлимит' if data.get('unlimited') is True else volume(data.get('total'))
        return (title + '\nОбновлена: ' + stamp(data.get('updated')) +
                '\nДействует до: ' + until + '\nТрафик: ' + volume(data.get('used')) + ' / ' + total +
                '\nПо данным последнего обновления подписки.')

    def diagnostics(self, uid, rid, epoch=None):
        data = self.router_call(uid, rid, 'xtlsbot-v1 diagnostics', epoch)
        def mib(value):
            return f'{value / 1024**2:.1f} МиБ' if type(value) in (int, float) and value >= 0 else 'нет данных'
        def yes(value):
            return 'да' if value is True else 'нет' if value is False else 'нет данных'
        text = (self.router_label(rid) + ' · Диагностика\n' +
                'Xray работает: ' + yes(data.get('running')) +
                '\nСетевой интерфейс поднят: ' + yes(data.get('interface_up')) +
                '\nПерехват трафика активен: ' + yes(data.get('interception_active')) +
                '\nДоступная RAM: ' + mib(data.get('memory_available')) +
                '\nRAM процесса Xray: ' + mib(data.get('rss')) +
                '\nПоследняя HTTPS-проверка успешна: ' + yes(data.get('proxy_ok')) +
                '\nЭто снимок состояния; новые сетевые проверки не запускались.')
        self.send_router(uid, rid, text, [[self.button(uid, rid, '🔄 Обновить', 'diagnostics')],
                         [self.button(uid, rid, '← Статус', 'status'),
                          self.button(uid, rid, '🏠 Мои роутеры', 'menu')]], epoch)

    def locations(self, uid, rid, epoch=None):
        self.authorize(uid, rid)
        data = self.router_call(uid, rid, 'xtlsbot-v1 locations', epoch)
        rows = []
        for node in data.get('nodes', [])[:60]:
            if not NODE.fullmatch(str(node.get('id', ''))):
                continue
            label = ('✅ ' if node.get('selected') else '') + str(node.get('name', 'Локация'))[:100]
            rows.append([self.button(uid, rid, label, 'select', node['id'])])
        rows.append([self.button(uid, rid, '⚡ Автовыбор', 'auto')])
        rows.append([self.button(uid, rid, '← Статус', 'status'),
                     self.button(uid, rid, '🏠 Мои роутеры', 'menu')])
        self.send_router(uid, rid, self.router_label(rid) + ' · Выберите локацию:', rows, epoch)

    def switch(self, uid, rid, action, target, update_id, epoch=None):
        job_id = None
        try:
            self.authorize(uid, rid)
            command = 'xtlsbot-v1 auto'
            if action == 'select':
                if not NODE.fullmatch(target):
                    raise SafeError('Недопустимая локация.')
                command = 'xtlsbot-v1 select ' + target
            receipt = self.router_call(uid, rid, command, epoch)
            job_id = receipt.get('job', {}).get('id', '')
            if receipt.get('accepted') is not True or not JOB.fullmatch(job_id):
                raise SafeError('Роутер не подтвердил приём задания.')
            self.store.finish(update_id, 'running', job_id)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                self.authorize(uid, rid)
                job = self.router_call(uid, rid, 'xtlsbot-v1 job ' + job_id, epoch).get('job', {})
                if job.get('id') != job_id:
                    raise SafeError('Задание заменено другой операцией. Проверьте статус.')
                if job.get('state') == 'done':
                    self.store.finish(update_id, 'done', job_id)
                    LOG.info('operation done update=%s router=%s action=%s', update_id, rid, action)
                    self.send_router(uid, rid, 'Роутер подтвердил применение настройки.', epoch=epoch)
                    self.status(uid, rid, epoch)
                    return
                if job.get('state') not in ('pending', 'running'):
                    raise SafeError('Применить настройку не удалось. Проверьте статус роутера.')
                time.sleep(2)
            raise SafeError('Истекло время ожидания задания. Результат не подтверждён; проверьте статус.')
        except SafeError as exc:
            self.store.finish(update_id, 'unconfirmed', job_id)
            self.inform(uid, str(exc))
        except Exception:
            self.store.finish(update_id, 'unconfirmed', job_id)
            LOG.error('operation internal error update=%s router=%s', update_id, rid)
            self.inform(uid, 'Результат операции не подтверждён. Проверьте статус.')
        finally:
            self.locks[rid].release()

    def admin_menu(self, uid, rid):
        self.admin(uid)
        self.authorize(uid, rid)
        self.store.cancel_admin(uid, rid)
        self.send_router(uid, rid, self.router_label(rid) + ' · Администрирование\nОперации могут временно прервать связь.', [
            [self.button(uid, rid, '✏️ Переименовать', 'rename_prompt')],
            [self.button(uid, rid, '🔧 Восстановить NetBird', 'admin_prompt', 'netbird')],
            [self.button(uid, rid, '🔧 Восстановить прокси', 'admin_prompt', 'proxy')],
            [self.button(uid, rid, '🔄 Перезагрузить роутер', 'admin_prompt', 'reboot')],
            [self.button(uid, rid, '⬅️ Статус', 'status')]])

    def admin_prompt(self, uid, rid, action, final=False):
        self.admin(uid)
        self.authorize(uid, rid)
        if action not in ('netbird', 'proxy', 'reboot'):
            raise SafeError('Недопустимая операция.')
        self.store.cancel_admin(uid, rid)
        labels = {'netbird': 'Перезапустить NetBird с сохранением регистрации',
                  'proxy': 'Восстановить прокси штатным контроллером',
                  'reboot': 'Перезагрузить роутер: интернет клиентов временно отключится'}
        button_action = 'admin_reboot_confirm' if action == 'reboot' and final else 'admin_confirm'
        text = self.router_label(rid) + '\n' + labels[action] + '?'
        if final:
            text += '\nПовторное подтверждение перезагрузки именно этого роутера.'
        self.send_router(uid, rid, text, [[self.button(uid, rid, '✅ Подтвердить', button_action, action)],
                                         [self.button(uid, rid, 'Отмена', 'admin_menu')]])

    def prepare_rescue(self, uid, rid):
        self.admin(uid)
        try:
            before = self.router_call(uid, rid, 'xtlsbot-v1 admin-status', transport='rescue')
            opened = self.router_call(uid, rid, 'xtlsbot-v1 admin-open-rescue', transport='rescue')
            if opened.get('ok') is not True:
                raise SafeError('Открытие аварийного канала не подтверждено.')
        except TransportError:
            # A live primary path can open the configured reserve for this
            # explicit admin request. Never reissue an ambiguous open request.
            opened = self.router_call(uid, rid, 'xtlsbot-v1 admin-open-rescue', transport='netbird')
            if opened.get('ok') is not True:
                raise SafeError('Открытие аварийного канала не подтверждено.')
            self.send_router(uid, rid, 'Открываем настроенный аварийный канал на 30 минут…')
            ready_deadline = time.monotonic() + 45
            while True:
                time.sleep(3)
                try:
                    before = self.router_call(uid, rid, 'xtlsbot-v1 admin-status', transport='rescue')
                    break
                except TransportError:
                    if time.monotonic() >= ready_deadline:
                        raise SafeError('Аварийный канал не открылся. Основная операция не отправлена.') from None
        return before

    def admin_operation(self, uid, rid, action, update_id):
        request = str(uuid.uuid4())
        try:
            self.admin(uid)
            before = self.prepare_rescue(uid, rid)
            boot = before.get('boot_id')
            if not isinstance(boot, str) or not JOB.fullmatch(boot):
                raise SafeError('Роутер не подтвердил идентификатор загрузки.')
            if action in ('netbird', 'reboot') and before.get('netbird_enabled') is not True:
                raise SafeError('Автозапуск NetBird не подтверждён. Операция отменена.')
            if action == 'reboot' and before.get('rescue_ready') is not True:
                raise SafeError('Автозапуск аварийного доступа не подтверждён. Перезагрузка отменена.')
            # Save the request before dispatch. A lost receipt is never retried.
            self.store.finish(update_id, 'running', request)
            receipt = self.router_call(uid, rid, 'xtlsbot-v1 admin ' + action + ' ' + request, transport='rescue')
            if receipt.get('accepted') is not True or receipt.get('id') != request or receipt.get('boot_id') != boot or receipt.get('action') != action:
                raise SafeError('Приём административного задания не подтверждён.')
            self.send_router(uid, rid, 'Роутер принял задание. ' + ('Ожидаем перезагрузку и возвращение связи…' if action == 'reboot' else 'Проверяем восстановление…'))
            deadline = time.monotonic() + (300 if action == 'reboot' else 240)
            restored = False
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    current = self.router_call(uid, rid, 'xtlsbot-v1 admin-status')
                except SafeError:
                    continue
                if action == 'reboot':
                    new_boot = current.get('boot_id')
                    if not isinstance(new_boot, str) or not JOB.fullmatch(new_boot) or new_boot == boot:
                        continue
                    if not restored:
                        self.send_router(uid, rid, 'Новая загрузка роутера подтверждена. SSH доступен; ожидаем проверку прокси…')
                        restored = True
                else:
                    job = current.get('job', {})
                    if job.get('id') != request or job.get('action') != action:
                        raise SafeError('Задание заменено. Результат не подтверждён.')
                    if job.get('state') in ('pending', 'running'):
                        continue
                    if job.get('state') != 'done':
                        raise SafeError('Восстановление не прошло проверку. Аварийный доступ остаётся настроенным.')
                try:
                    if action == 'netbird':
                        if current.get('netbird_connected') is not True:
                            continue
                        status = self.router_call(uid, rid, 'xtlsbot-v1 status', transport='netbird')
                    else:
                        status = self.router_call(uid, rid, 'xtlsbot-v1 status')
                        if status.get('running') is not True or status.get('proxy_ok') is not True:
                            continue
                        if action == 'reboot' and current.get('netbird_connected') is not True:
                            continue
                except SafeError:
                    continue
                self.store.finish(update_id, 'done', request)
                LOG.info('admin operation done update=%s router=%s action=%s', update_id, rid, action)
                message = {'netbird': 'NetBird восстановлен: Management/Signal подключены, SSH через NetBird проверен.',
                           'proxy': 'Прокси восстановлен. Проверка HTTPS успешна.',
                           'reboot': 'Перезагрузка подтверждена. NetBird подключён, проверка прокси успешна.'}[action]
                self.send_router(uid, rid, message)
                self.status(uid, rid)
                return
            raise SafeError('Время ожидания истекло. Результат не подтверждён; операция повторно не отправлена.')
        except SafeError as error:
            self.store.finish(update_id, 'unconfirmed', request)
            self.inform(uid, self.router_label(rid) + '\n' + str(error))
        except Exception:
            self.store.finish(update_id, 'unconfirmed', request)
            LOG.error('admin operation unconfirmed update=%s router=%s', update_id, rid)
            self.inform(uid, 'Результат административной операции не подтверждён. Проверьте статус роутера.')
        finally:
            self.locks[rid].release()

    def updates_menu(self, uid, rid, epoch=None):
        self.admin(uid)
        self.authorize(uid, rid)
        self.store.cancel_admin(uid, rid)
        data = self.router_call(uid, rid, 'xtlsbot-v1 updates')
        plans = {p.get('component'): p for p in data.get('plans', []) if isinstance(p, dict)}
        text = self.router_label(rid) + ' · Обновления\nТолько стабильные релизы. Прошивка OpenWrt обновляется отдельно.'
        rows = []
        for component, label in (('app', 'Приложение'), ('xray', 'Xray'), ('netbird', 'NetBird')):
            p = plans.get(component)
            if p:
                text += '\n\n' + label + ': ' + str(p.get('installed') or 'нет пакетной версии')[:64]
                text += '\nДоступно: ' + str(p.get('available') or 'нет данных')[:64]
                text += ' · ' + ('есть обновление' if p.get('update_available') else 'обновление не требуется')
                if not p.get('valid'):
                    text += '\nПроверка устарела — проверьте заново.'
            else:
                text += '\n\n' + label + ': проверка ещё не выполнена.'
            rows.append([self.button(uid, rid, '🔎 Проверить ' + label, 'update_check', component)])
            if p and p.get('valid') is True and p.get('update_available') is True and isinstance(p.get('id'), str) and JOB.fullmatch(p['id']):
                rows.append([self.button(uid, rid, '⬆️ Обновить ' + label, 'update_prompt', component + ':' + p['id'])])
        rows.append([self.button(uid, rid, '⬅️ Статус', 'status')])
        self.send_router(uid, rid, text, rows)

    def update_prompt(self, uid, rid, target):
        self.admin(uid)
        match = re.fullmatch(r'(app|xray|netbird):([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})', target)
        if not match:
            raise SafeError('Недопустимый план обновления.')
        data = self.router_call(uid, rid, 'xtlsbot-v1 updates')
        p = next((p for p in data.get('plans', []) if isinstance(p, dict) and p.get('component') == match[1] and p.get('id') == match[2]), None)
        if not p or p.get('valid') is not True or p.get('update_available') is not True:
            raise SafeError('План устарел. Откройте обновления и выполните проверку заново.')
        self.store.cancel_admin(uid, rid)
        label = {'app': 'Приложение', 'xray': 'Xray', 'netbird': 'NetBird'}[match[1]]
        self.send_router(uid, rid, self.router_label(rid) + '\n' + label + ': ' + str(p.get('installed'))[:64] + ' → ' + str(p.get('available'))[:64] +
            '\nУстановить именно эту версию? Связь может временно прерваться.',
            [[self.button(uid, rid, '✅ Установить', 'update_install', target)],
             [self.button(uid, rid, 'Отмена', 'updates')]])

    def update_operation(self, uid, rid, component, action, plan, update_id):
        request = str(uuid.uuid4())
        try:
            self.admin(uid)
            if action == 'install':
                self.prepare_rescue(uid, rid)
            self.store.finish(update_id, 'running', request)
            command = 'xtlsbot-v1 update-' + action + ' ' + component + ' ' + request
            if action == 'install':
                command += ' ' + plan
            receipt = self.router_call(uid, rid, command, transport='rescue' if action == 'install' else None)
            if receipt.get('accepted') is not True or receipt.get('id') != request or receipt.get('component') != component or receipt.get('action') != action:
                raise SafeError('Приём задания обновления не подтверждён.')
            self.send_router(uid, rid, 'Роутер принял задание. ' + ('Проверяем каталог…' if action == 'check' else 'Устанавливаем выбранную версию и проверяем работу…'))
            deadline = time.monotonic() + (1500 if action == 'install' else 750)
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    data = self.router_call(uid, rid, 'xtlsbot-v1 updates')
                except SafeError:
                    continue
                job = data.get('job', {})
                if job.get('id') != request or job.get('component') != component or job.get('action') != action:
                    raise SafeError('Задание обновления заменено или прервано. Проверьте версии.')
                if job.get('state') in ('pending', 'running'):
                    continue
                if job.get('state') != 'done':
                    reason = {'native': 'Установщик не подтвердил завершение.',
                              'version': 'Не подтверждена выбранная версия.',
                              'settings': 'Проверка сохранности настроек не пройдена.',
                              'https': 'Проверка HTTPS через прокси не пройдена.',
                              'dns_udp': 'Проверка DNS по UDP не пройдена.',
                              'dns_tcp': 'Проверка DNS по TCP не пройдена.'}.get(job.get('reason'), '')
                    raise SafeError('Операция обновления не подтверждена. ' + (reason + ' ' if reason else '') + 'Проверьте версии и диагностику роутера; повторная установка автоматически не запускается.')
                if action == 'install':
                    status = self.router_call(uid, rid, 'xtlsbot-v1 status')
                    nb = self.router_call(uid, rid, 'xtlsbot-v1 admin-status')
                    if status.get('proxy_ok') is not True or nb.get('netbird_connected') is not True:
                        continue
                    if component == 'netbird':
                        self.router_call(uid, rid, 'xtlsbot-v1 status', transport='netbird')
                self.store.finish(update_id, 'done', request)
                LOG.info('update operation done update=%s router=%s component=%s action=%s', update_id, rid, component, action)
                self.send_router(uid, rid, 'Проверка версий завершена.' if action == 'check' else 'Выбранная версия установлена. Проверки версии, настроек, HTTPS и DNS пройдены; NetBird подключён.')
                self.updates_menu(uid, rid)
                return
            raise SafeError('Результат обновления не подтверждён за отведённое время. Команда повторно не отправлена; проверьте версии.')
        except SafeError as error:
            self.store.finish(update_id, 'unconfirmed', request)
            self.inform(uid, self.router_label(rid) + '\n' + str(error))
        except Exception:
            self.store.finish(update_id, 'unconfirmed', request)
            LOG.error('update operation unconfirmed update=%s router=%s', update_id, rid)
            self.inform(uid, 'Результат обновления не подтверждён. Проверьте версии на роутере.')
        finally:
            self.locks[rid].release()

    def access(self, uid, rid):
        self.admin(uid)
        self.authorize(uid, rid)
        self.store.clear_dialog(uid)
        self.store.cancel_confirmations(uid, rid)
        clients = self.store.clients(rid)
        lines = [self.router_label(rid) + ' · Доступ клиентов',
                 'ID роутера: ' + rid]
        lines.extend('• ' + self.user_label(client) for client in clients[:40])
        if not clients:
            lines.append('Клиенты пока не привязаны.')
        lines.append('Добавьте клиента или выберите, чей доступ отозвать.')
        rows = [[self.button(uid, rid, 'Отозвать ' + self.store.user_info(client)[0], 'revoke_prompt', str(client))]
                for client in clients[:40]]
        rows.insert(0, [self.button(uid, rid, '➕ Добавить клиента', 'grant_input')])
        rows.append([self.button(uid, rid, '← Статус', 'status'),
                     self.button(uid, rid, '🏠 Мои роутеры', 'menu')])
        self.send(uid, '\n'.join(lines), rows)

    def access_prompt(self, uid, rid, target, grant):
        self.admin(uid)
        self.authorize(uid, rid)
        target = self.store.resolve_user(target)
        if not re.fullmatch(r'[1-9][0-9]{0,15}', target) or not 0 < int(target) < 2**52:
            raise SafeError('Укажите числовой Telegram ID клиента.')
        if int(target) == self.config['admin_id']:
            raise SafeError('Администратор уже имеет доступ ко всем роутерам.')
        verb = 'Выдать' if grant else 'Отозвать'
        text = (verb + ' доступ к ' + self.router_label(rid) +
                ' для ' + self.user_label(int(target)) + '?')
        if not grant:
            text += '\nУже принятое роутером задание может завершиться.'
        rows = [[self.button(uid, rid, 'Подтвердить', 'grant' if grant else 'revoke', target)],
                [self.button(uid, rid, 'Отмена', 'access')]]
        self.send(uid, text, rows)

    def grant_input(self, uid, rid):
        self.admin(uid)
        self.authorize(uid, rid)
        self.store.cancel_confirmations(uid, rid)
        self.store.set_dialog(uid, rid)
        text = ('Добавить клиента к ' + self.router_label(rid) +
                '\nОтправьте числовой Telegram ID клиента. Номер подписки не используется для выдачи доступа.'
                '\nКлиент видит свой ID при первом запуске бота.'
                '\nПосле ввода появится подтверждение. Ожидание — 10 минут.')
        self.send(uid, text, [[self.button(uid, rid, 'Отмена', 'access')]])

    def operator_menu(self, uid, rid):
        self.admin(uid)
        self.store.operator_dialog(uid,'clear')
        self.send(uid,'Администрирование бота',[
            [self.button(uid,rid,'➕ Добавить роутер','operator_add')],
            [self.button(uid,rid,'🔐 Создать бэкап','operator_backup')],
            [self.button(uid,rid,'🏠 Мои роутеры','menu')]])

    def operator_submit(self, uid, action, code='', name=''):
        self.admin(uid)
        from operator_client import request
        job=self.store.operator_start(uid,action)
        try:request(action,uid,code,name,job=job)
        except Exception:
            self.store.operator_finish(job,'failed')
            raise SafeError('Не удалось передать задание. Проверьте установку административного обработчика.') from None
        self.send(uid,'Задание принято. '+('Проверяем устройство и аварийный канал; регистрация может занять до нескольких минут…' if action=='enroll' else 'Создаём и проверяем зашифрованную резервную копию…'))

    def operator_input(self, uid, text, dialog):
        self.admin(uid)
        if dialog['stage'] == 'rename':
            rid = dialog['name']
            self.authorize(uid, rid)
            self.store.rename_router(uid, rid, text)
            self.store.operator_dialog(uid, 'clear')
            self.send(uid, 'Имя сохранено: ' + self.router_name(rid),
                      [[self.button(uid, rid, '⬅️ Статус', 'status')]])
            return
        from operator_client import valid_name,router_command
        if dialog['stage']=='name':
            if not valid_name(text):raise SafeError('Имя: от 1 до 80 символов, без переводов строк.')
            try:command=router_command(self.config)
            except Exception:raise SafeError('Профиль подключения ещё не настроен на VPS.') from None
            self.store.operator_dialog(uid,'code',text)
            self.send(uid,'Выполните следующий блок целиком на роутере через SSH. Затем отправьте сюда только полученный код xtls-pair-v1. Ожидание — 15 минут.')
            self.send(uid,command)
        elif dialog['stage']=='code':
            if not re.fullmatch(r'xtls-pair-v1:[0-9.]+:[0-9]{1,5}:[A-Za-z0-9+/]{43}',text):
                raise SafeError('Отправьте только короткий код xtls-pair-v1, выданный роутером.')
            self.operator_submit(uid,'enroll',text,dialog['name'])
            self.store.operator_dialog(uid,'clear')

    def deliver_operator_results(self):
        jobs=self.store.operator_pending()
        if not jobs:return
        from operator_client import result,CONFIG
        for job in jobs:
            try:value=result(job['id'])
            except (OSError,ValueError):value=None
            if value and value.get('state') in ('done','failed'):
                if value['state']=='done' and job['action']=='enroll':
                    with self.policy_lock:
                        current=load_config(CONFIG)
                        self.config=current
                        self.bridge.config=current
                        for rid in current['routers']:
                            self.locks.setdefault(rid,threading.Lock())
                            self.store.router_code(rid)
                self.send(job['uid'],str(value.get('text','Операция завершена.'))[:3900])
                self.store.operator_finish(job['id'],value['state'])
                if value['state']=='done' and job['action']=='enroll':self.menu(job['uid'])
            elif time.time()-job['created']>1200:
                self.send(job['uid'],'Результат административной операции не подтверждён. Проверьте состояние на VPS; автоматического повтора нет.')
                self.store.operator_finish(job['id'],'unknown')

    def help(self, uid):
        self.authorize(uid)
        text = ('Выберите роутер, затем откройте «Локации» или нажмите «Автовыбор».'
                '\nВ «Мои роутеры» нажмите «Поиск»: имя, полный или частичный HWID, номер подписки.'
                '\nПоиск не зависит от регистра и дефисов HWID. /start сбрасывает поиск.')
        if uid == self.config['admin_id']:
            text += ('\n\nВыдача доступа: роутер → «Доступ клиентов» → «Добавить клиента».'
                     '\nОтзыв: «Доступ клиентов» → «Отозвать» рядом с Telegram ID.'
                     '\n\nЗапасные команды: /start, /whoami, /help'
                     '\n/bind ROUTER_ID TELEGRAM_ID'
                     '\n/unbind ROUTER_ID TELEGRAM_ID'
                     '\n/access ROUTER_ID\nРоутеры:\n' +
                     '\n'.join(rid + ' — ' + self.router_name(rid) for rid, r in self.config['routers'].items()))
        first = next(rid for rid in self.config['routers'] if rid in self.visible(uid))
        self.send(uid, text, ([] if uid == self.config['admin_id'] else [[self.support_button()]]) + [[self.button(uid, first, '🏠 Мои роутеры', 'menu')]])

    def admin_command(self, uid, text):
        self.admin(uid)
        match = re.fullmatch(r'/(bind|unbind) ([a-z0-9_-]{1,32}) ([1-9][0-9]{0,15})', text)
        if match:
            action, rid, target = match.groups()
            self.access_prompt(uid, rid, target, action == 'bind')
            return
        match = re.fullmatch(r'/access ([a-z0-9_-]{1,32})', text)
        if match:
            self.access(uid, match[1])
            return
        raise SafeError('Формат: /bind ROUTER_ID TELEGRAM_ID или /unbind ROUTER_ID TELEGRAM_ID. Справка: /help')

    def handle(self, update):
        callback = update.get('callback_query')
        message = callback.get('message', {}) if callback else update.get('message', {})
        uid = (callback or message).get('from', {}).get('id')
        chat = message.get('chat', {})
        if (chat.get('type') != 'private' or chat.get('id') != uid or
                type(uid) is not int or not 0 < uid < 2**52):
            if callback:
                self.tg.call('answerCallbackQuery', callback_query_id=callback['id'], text='Только в личном чате.')
            return
        sender = (callback or message).get('from', {})
        self.store.user_info(uid, ' '.join(str(sender.get(k, '')) for k in ('first_name', 'last_name')).strip() or None)
        if not self.visible(uid):
            if callback:
                self.tg.call('answerCallbackQuery', callback_query_id=callback['id'], text='Доступ запрещён.')
            else:
                self.inform(uid, 'xtlsproVPN · Управление роутером\n' + self.identity(uid) +
                            '\nДоступ к роутеру пока не выдан. Передайте этот ID администратору.',
                            [[self.support_button()]])
            return
        try:
            if not callback:
                text = message.get('text', '').strip()
                operator_dialog=self.store.operator_dialog(uid) if uid==self.config['admin_id'] else None
                if operator_dialog and not text.startswith('/'):
                    self.operator_input(uid,text,operator_dialog)
                    return
                if uid==self.config['admin_id']:self.store.operator_dialog(uid,'clear')
                dialog = self.store.dialog(uid) if uid == self.config['admin_id'] else None
                catalog = self.store.catalog(uid)
                if catalog['awaiting'] and not text.startswith('/'):
                    self.menu(uid, query=text, page=0)
                    return
                self.store.catalog(uid, catalog['query'], catalog['page'])
                if dialog and not text.startswith('/'):
                    self.access_prompt(uid, dialog, text, True)
                    self.store.clear_dialog(uid)
                elif text == '/whoami':
                    self.store.clear_dialog(uid)
                    self.inform(uid, self.identity(uid))
                elif text == '/help':
                    self.store.clear_dialog(uid)
                    self.help(uid)
                elif text.startswith(('/bind', '/unbind', '/access')):
                    self.store.clear_dialog(uid)
                    self.admin_command(uid, text)
                else:
                    self.store.clear_dialog(uid)
                    self.menu(uid, query='', page=0)
                return
            with self.read_guard:
                busy = uid in self.read_busy
            if busy:
                self.tg.call('answerCallbackQuery', callback_query_id=callback['id'], text='Запрос обрабатывается…')
                return
            try:
                button = self.store.take_button(callback.get('data'), uid)
            except SafeError:
                self.tg.call('answerCallbackQuery', callback_query_id=callback['id'], text='Кнопка уже использована или устарела.')
                return
            self.tg.call('answerCallbackQuery', callback_query_id=callback['id'], text='Обрабатываем…')
            rid, action, target = button['router'], button['action'], button['target']
            epoch = button['grant_epoch']
            self.authorize(uid, rid, epoch)
            catalog = self.store.catalog(uid)
            self.store.catalog(uid, catalog['query'], catalog['page'])
            self.store.clear_dialog(uid)
            if uid==self.config['admin_id']:self.store.operator_dialog(uid,'clear')
            if action == 'rename_prompt':
                self.admin(uid)
                self.store.operator_dialog(uid, 'rename', rid)
                self.send(uid, 'Введите новое имя роутера (1–80 символов). Ожидание — 15 минут.',
                          [[self.button(uid, rid, 'Отмена', 'admin_menu')]])
            elif action == 'operator_menu':
                self.operator_menu(uid,rid)
            elif action == 'operator_add':
                self.admin(uid)
                self.store.operator_dialog(uid,'name')
                self.send(uid,'Введите имя роутера, например HOME или Клиент 1481 · Москва.',[[self.button(uid,rid,'Отмена','operator_menu')]])
            elif action == 'operator_backup':
                self.operator_submit(uid,'backup')
            elif action == 'catalog_search':
                self.store.catalog(uid, catalog['query'], catalog['page'], awaiting=True)
                self.send(uid, 'Введите имя роутера, HWID целиком или частично, либо номер подписки. Например: HOME, 242c-7c6d или 1481.\nОжидание — 15 минут.',
                          [[self.button(uid, rid, 'Отмена', 'menu')]])
            elif action == 'catalog_page':
                try:
                    query, page = json.loads(target)
                except (ValueError, TypeError):
                    raise SafeError('Некорректная страница каталога.') from None
                self.menu(uid, query=query, page=page)
            elif action == 'catalog_all':
                self.menu(uid, query='', page=0)
            elif action == 'menu':
                self.menu(uid)
            elif action == 'help':
                self.help(uid)
            elif action == 'whoami':
                self.inform(uid, self.identity(uid))
            elif action == 'status':
                self.submit_read(uid, rid, 'status', epoch)
            elif action == 'locations':
                self.submit_read(uid, rid, 'locations', epoch)
            elif action == 'diagnostics':
                self.submit_read(uid, rid, 'diagnostics', epoch)
            elif action == 'monitor':
                self.monitor_menu(uid, rid)
            elif action in ('monitor_on', 'monitor_off'):
                self.admin(uid)
                self.store.monitor_enable(rid, action == 'monitor_on')
                self.monitor_menu(uid, rid)
            elif action == 'updates':
                self.admin(uid)
                self.submit_read(uid, rid, 'updates', epoch)
            elif action == 'update_prompt':
                self.admin(uid)
                self.submit_read(uid, rid, 'update_prompt', epoch, target)
            elif action in ('update_check', 'update_install'):
                self.admin(uid)
                component, plan = target, ''
                if action == 'update_install':
                    match = re.fullmatch(r'(app|xray|netbird):([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})', target)
                    if not match:
                        raise SafeError('Недопустимый план обновления.')
                    component, plan = match.groups()
                if component not in ('app', 'xray', 'netbird'):
                    raise SafeError('Недопустимый компонент.')
                if not self.locks[rid].acquire(blocking=False):
                    raise SafeError('Операция уже выполняется. Дождитесь результата.')
                try:
                    begun = self.store.begin_admin(update['update_id'], uid, rid, 'update_' + component) if action == 'update_install' else self.store.begin(update['update_id'], uid, rid, 'check_' + component, '')
                    if not begun:
                        self.locks[rid].release()
                        return
                    self.store.cancel_admin(uid, rid)
                    self.send_router(uid, rid, 'Подготавливаем ' + ('проверку каталога…' if action == 'update_check' else 'установку через аварийный канал…'))
                    self.pool.submit(self.update_operation, uid, rid, component, 'check' if action == 'update_check' else 'install', plan, update['update_id'])
                except Exception:
                    self.store.finish(update['update_id'], 'interrupted')
                    self.locks[rid].release()
                    raise
            elif action == 'admin_menu':
                self.admin_menu(uid, rid)
            elif action == 'admin_prompt':
                self.admin_prompt(uid, rid, target)
            elif action in ('admin_confirm', 'admin_reboot_confirm', 'update_install'):
                self.admin(uid)
                if target not in ('netbird', 'proxy', 'reboot'):
                    raise SafeError('Недопустимая операция.')
                if target == 'reboot' and action == 'admin_confirm':
                    self.admin_prompt(uid, rid, target, final=True)
                    return
                if action == 'admin_reboot_confirm' and target != 'reboot':
                    raise SafeError('Недопустимая операция.')
                if not self.locks[rid].acquire(blocking=False):
                    raise SafeError('Операция уже выполняется. Дождитесь результата.')
                try:
                    if not self.store.begin_admin(update['update_id'], uid, rid, target):
                        self.locks[rid].release()
                        return
                    self.store.cancel_admin(uid, rid)
                    self.send_router(uid, rid, 'Проверяем аварийный канал и условия операции…')
                    self.pool.submit(self.admin_operation, uid, rid, target, update['update_id'])
                except Exception:
                    self.store.finish(update['update_id'], 'interrupted')
                    self.locks[rid].release()
                    raise
            elif action == 'access':
                self.access(uid, rid)
            elif action == 'grant_input':
                self.grant_input(uid, rid)
            elif action == 'revoke_prompt':
                self.access_prompt(uid, rid, target, False)
            elif action in ('grant', 'revoke'):
                self.admin(uid)
                if not re.fullmatch(r'[1-9][0-9]{0,15}', target) or not 0 < int(target) < 2**52:
                    raise SafeError('Недопустимый Telegram ID.')
                if int(target) == self.config['admin_id']:
                    raise SafeError('Права администратора не изменяются.')
                with self.policy_lock:
                    self.store.change_access(uid, int(target), rid, action == 'grant')
                self.send(uid, 'Доступ выдан.' if action == 'grant' else 'Доступ отозван. Старые кнопки клиента недействительны.')
                self.access(uid, rid)
                self.deliver_notifications()
            elif action in ('select', 'auto'):
                if not self.locks[rid].acquire(blocking=False):
                    raise SafeError('Операция уже выполняется. Дождитесь результата.')
                if not self.store.begin(update['update_id'], uid, rid, action, target):
                    self.locks[rid].release()
                    return
                try:
                    self.send_router(uid, rid, 'Запрос принят. Ожидаем подтверждение роутера…', epoch=epoch)
                    self.pool.submit(self.switch, uid, rid, action, target, update['update_id'], epoch)
                except Exception:
                    self.store.finish(update['update_id'], 'interrupted')
                    self.locks[rid].release()
                    raise
            else:
                raise SafeError('Недопустимая операция.')
        except SafeError as exc:
            self.inform(uid, str(exc))

    def run(self):
        me = self.tg.call('getMe')
        if me.get('username', '').lower() != self.config['bot_username']:
            raise SafeError('Токен принадлежит другому боту.')
        if self.tg.call('getWebhookInfo').get('url'):
            raise SafeError('У бота настроен webhook. Автоматически отключать его запрещено.')
        threading.Thread(target=self.monitor_loop, name='router-monitor', daemon=True).start()
        LOG.info('pilot started routers=%d', len(self.config['routers']))
        while True:
            try:
                self.deliver_notifications()
                self.deliver_operator_results()
                updates = self.tg.call('getUpdates', offset=self.store.offset(), timeout=10,
                                       allowed_updates=['message', 'callback_query'], limit=20)
                for update in updates:
                    # Persist before handling: a crash may lose a request, never replay it.
                    self.store.checkpoint(update['update_id'])
                    try:
                        self.handle(update)
                    except Exception:
                        LOG.error('update not completed id=%s', update.get('update_id'))
            except SafeError:
                LOG.warning('Telegram polling unavailable; retrying')
                time.sleep(5)


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        config = load_config('/etc/xtls-router-bot/config.json')
        token = (Path(os.environ['CREDENTIALS_DIRECTORY']) / 'telegram_token').read_text().strip()
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
            raise SafeError('Некорректный формат токена.')
        Bot(config, Telegram(token), Store(config['database']), Bridge(config)).run()
    except Exception:
        LOG.error('Bot startup failed; check config, credential, bot username and webhook state')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
