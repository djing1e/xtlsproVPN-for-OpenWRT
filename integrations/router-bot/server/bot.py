#!/usr/bin/python3
"""Administrator and client router pilot. No arbitrary SSH or Telegram shell commands."""
import concurrent.futures
from contextlib import contextmanager
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
import urllib.error
import urllib.request

LOG = logging.getLogger('xtls-router-bot')
NODE = re.compile(r'cfg[A-Za-z0-9_-]{6}\Z')
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
                raise SafeError('Telegram отклонил запрос.')
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
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY, uid INTEGER, router TEXT, granted INTEGER,
                    epoch TEXT, state TEXT DEFAULT 'pending', retry_at INTEGER DEFAULT 0);
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
                       (token, uid, router, action, target, now + 900, grant_epoch))
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

    def finish(self, update_id, state, job=None):
        with self.connect() as db:
            db.execute('UPDATE operations SET state=?,job=coalesce(?,job) WHERE update_id=?',
                       (state, job, update_id))


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
            '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
            '-o', 'ClearAllForwardings=yes',
            '-i', config['ssh_key'], '-p', str(router['port']),
            'root@' + router['host'], command]


class Bridge:
    def __init__(self, config):
        self.config = config

    def call(self, router, command):
        allowed = command in ('xtlsbot-v1 status', 'xtlsbot-v1 locations', 'xtlsbot-v1 auto')
        allowed |= bool(re.fullmatch(r'xtlsbot-v1 select cfg[A-Za-z0-9_-]{6}', command))
        allowed |= bool(re.fullmatch(r'xtlsbot-v1 job [a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', command))
        if not allowed:
            raise SafeError('Недопустимая операция.')
        try:
            result = subprocess.run(ssh_command(self.config, router, command),
                                    capture_output=True, timeout=23)
            # Never send raw SSH stderr, config or router response to Telegram.
            if len(result.stdout) > 262144:
                raise SafeError('Некорректный ответ роутера.')
            reply = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise SafeError('Нет ответа от роутера по SSH.') from None
        if not isinstance(reply, dict) or reply.get('schema') != 1:
            raise SafeError('Версия обработчика роутера не поддерживается.')
        if result.returncode or reply.get('ok') is not True:
            code = reply.get('error', {}).get('code')
            messages = {
                'busy': 'На роутере уже выполняется операция. Повторите позже.',
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
    for rid, router in config['routers'].items():
        if not re.fullmatch(r'[a-z0-9_-]{1,32}', rid):
            raise ValueError('router id')
        ipaddress.ip_address(router['host'])
        if type(router.get('port')) is not int or not 1 <= router['port'] <= 65535:
            raise ValueError('router port')
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

    def router_label(self, rid):
        return self.store.router_code(rid) + ' · ' + self.config['routers'][rid]['name']

    def user_label(self, uid):
        code, name = self.store.user_info(uid)
        return code + (' · ' + name if name else '') + ' · Telegram ID ' + str(uid)

    def identity(self, uid):
        return 'Ваш ID: ' + self.store.user_info(uid)[0] + '\nTelegram ID: ' + str(uid)

    def submit_read(self, uid, rid, action, epoch):
        with self.read_guard:
            if uid in self.read_busy:
                return
            self.read_busy.add(uid)
        def work():
            try:
                (self.status if action == 'status' else self.locations)(uid, rid, epoch)
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

    def deliver_notifications(self):
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

    def router_call(self, uid, rid, command, epoch=None):
        # Serialize revocation with authorization and SSH dispatch. A command
        # already accepted by the router may finish; no subsequent dispatch occurs.
        with self.policy_lock:
            self.authorize(uid, rid, epoch)
            result = self.bridge.call(self.config['routers'][rid], command)
            self.authorize(uid, rid, epoch)
            return result

    def send_router(self, uid, rid, text, keyboard=None, epoch=None):
        with self.policy_lock:
            self.authorize(uid, rid, epoch)
            self.send(uid, text, keyboard)

    def inform(self, uid, text):
        # Public private-chat response: own ID/help only, never router data.
        self.tg.call('sendMessage', chat_id=uid, text=text[:4000])

    def send(self, uid, text, keyboard=None):
        self.authorize(uid)
        args = {'chat_id': uid, 'text': text[:4000]}
        if keyboard is not None:
            args['reply_markup'] = {'inline_keyboard': keyboard}
        self.tg.call('sendMessage', **args)

    def button(self, uid, rid, text, action, target=''):
        self.authorize(uid, rid)
        epoch = '' if uid == self.config['admin_id'] else self.store.grant_epoch(uid, rid)
        return {'text': text, 'callback_data': self.store.button(uid, rid, action, target, epoch)}

    def menu(self, uid):
        rows = [[self.button(uid, rid, self.router_label(rid), 'status')]
                for rid, router in self.config['routers'].items() if rid in self.visible(uid)]
        if rows:
            first = next(rid for rid in self.config['routers'] if rid in self.visible(uid))
            rows.append([self.button(uid, first, '🆔 Мой ID', 'whoami'),
                         self.button(uid, first, 'ℹ️ Помощь', 'help')])
        self.send(uid, 'xtlsproVPN · Управление роутерами\nВыберите роутер:', rows)

    def status(self, uid, rid, epoch=None):
        self.authorize(uid, rid)
        router = self.config['routers'][rid]
        data = self.router_call(uid, rid, 'xtlsbot-v1 status', epoch)
        locations = self.router_call(uid, rid, 'xtlsbot-v1 locations', epoch)
        names = [str(n.get('name', 'Локация'))[:120] for n in locations.get('nodes', [])
                 if n.get('id') in data.get('selected', [])]
        mode = 'Автовыбор' if data.get('mode') == 'auto' else 'Ручной'
        running = 'работает' if data.get('running') else 'остановлен'
        # Cached health is explicitly labelled; selection success isn't a new probe.
        health = {True: 'успешна', False: 'ошибка', None: 'нет данных'}.get(data.get('proxy_ok'), 'нет данных')
        text = (f"{self.router_label(rid)}\nПрокси: {running}\nРежим: {mode}\n"
                f"Локация: {', '.join(names) or 'нет данных'}\n"
                f"Последняя проверка прокси: {health}\nВерсия: {str(data.get('version', '—'))[:40]}")
        rows = [[self.button(uid, rid, '🌍 Локации', 'locations'),
                 self.button(uid, rid, '🔄 Статус', 'status')],
                [self.button(uid, rid, '⚡ Автовыбор', 'auto')]]
        if uid == self.config['admin_id']:
            rows.append([self.button(uid, rid, '👥 Доступ клиентов', 'access')])
        rows.append([self.button(uid, rid, '🏠 Мои роутеры', 'menu')])
        self.send_router(uid, rid, text, rows, epoch)

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
                '\nОтправьте ID клиента вида U-000001 или числовой Telegram ID.'
                '\nКлиент видит свой ID при первом запуске бота.'
                '\nПосле ввода появится подтверждение. Ожидание — 10 минут.')
        self.send(uid, text, [[self.button(uid, rid, 'Отмена', 'access')]])

    def help(self, uid):
        self.authorize(uid)
        text = ('Выберите роутер, затем откройте «Локации» или нажмите «Автовыбор».'
                '\nКнопка «Мои роутеры» возвращает в главное меню.')
        if uid == self.config['admin_id']:
            text += ('\n\nВыдача доступа: роутер → «Доступ клиентов» → «Добавить клиента».'
                     '\nОтзыв: «Доступ клиентов» → «Отозвать» рядом с Telegram ID.'
                     '\n\nЗапасные команды: /start, /whoami, /help'
                     '\n/bind ROUTER_ID TELEGRAM_ID'
                     '\n/unbind ROUTER_ID TELEGRAM_ID'
                     '\n/access ROUTER_ID\nРоутеры:\n' +
                     '\n'.join(rid + ' — ' + r['name'] for rid, r in self.config['routers'].items()))
        first = next(rid for rid in self.config['routers'] if rid in self.visible(uid))
        self.send(uid, text, [[self.button(uid, first, '🏠 Мои роутеры', 'menu')]])

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
                            '\nДоступ к роутеру пока не выдан. Передайте этот ID администратору.')
            return
        try:
            if not callback:
                text = message.get('text', '').strip()
                dialog = self.store.dialog(uid) if uid == self.config['admin_id'] else None
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
                    self.menu(uid)
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
            self.store.clear_dialog(uid)
            if action == 'menu':
                self.menu(uid)
            elif action == 'help':
                self.help(uid)
            elif action == 'whoami':
                self.inform(uid, self.identity(uid))
            elif action == 'status':
                self.submit_read(uid, rid, 'status', epoch)
            elif action == 'locations':
                self.submit_read(uid, rid, 'locations', epoch)
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
        LOG.info('pilot started routers=%d', len(self.config['routers']))
        while True:
            try:
                self.deliver_notifications()
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
