#!/usr/bin/python3
"""Single-administrator LAB pilot. No arbitrary SSH or Telegram shell commands."""
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

    def button(self, uid, router, action, target=''):
        token = secrets.token_urlsafe(18)
        with self.connect() as db:
            now = int(time.time())
            db.execute('DELETE FROM buttons WHERE expires < ?', (now,))
            db.execute('INSERT INTO buttons(token,uid,router,action,target,expires) VALUES (?,?,?,?,?,?)',
                       (token, uid, router, action, target, now + 900))
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
            if row['action'] in ('select', 'auto'):
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

    def authorize(self, uid, router=None):
        # Pilot: only the configured numeric administrator ID; no client enrollment.
        if type(uid) is not int or uid != self.config['admin_id']:
            raise SafeError('Доступ запрещён.')
        if router is not None and router not in self.config['routers']:
            raise SafeError('Роутер недоступен.')

    def send(self, uid, text, keyboard=None):
        self.authorize(uid)
        args = {'chat_id': uid, 'text': text[:4000]}
        if keyboard is not None:
            args['reply_markup'] = {'inline_keyboard': keyboard}
        self.tg.call('sendMessage', **args)

    def button(self, uid, rid, text, action, target=''):
        return {'text': text, 'callback_data': self.store.button(uid, rid, action, target)}

    def menu(self, uid):
        rows = [[self.button(uid, rid, router['name'], 'status')]
                for rid, router in self.config['routers'].items()]
        self.send(uid, 'xtlsproVPN · Управление роутерами\nВыберите роутер:', rows)

    def status(self, uid, rid):
        self.authorize(uid, rid)
        router = self.config['routers'][rid]
        data = self.bridge.call(router, 'xtlsbot-v1 status')
        locations = self.bridge.call(router, 'xtlsbot-v1 locations')
        names = [str(n.get('name', 'Локация'))[:120] for n in locations.get('nodes', [])
                 if n.get('id') in data.get('selected', [])]
        mode = 'Автовыбор' if data.get('mode') == 'auto' else 'Ручной'
        running = 'работает' if data.get('running') else 'остановлен'
        # Cached health is explicitly labelled; selection success isn't a new probe.
        health = {True: 'успешна', False: 'ошибка', None: 'нет данных'}.get(data.get('proxy_ok'), 'нет данных')
        text = (f"{router['name']}\nПрокси: {running}\nРежим: {mode}\n"
                f"Локация: {', '.join(names) or 'нет данных'}\n"
                f"Последняя проверка прокси: {health}\nВерсия: {str(data.get('version', '—'))[:40]}")
        self.send(uid, text, [[self.button(uid, rid, '🌍 Локации', 'locations'),
                              self.button(uid, rid, '🔄 Статус', 'status')],
                             [self.button(uid, rid, '⚡ Автовыбор', 'auto')]])

    def locations(self, uid, rid):
        self.authorize(uid, rid)
        data = self.bridge.call(self.config['routers'][rid], 'xtlsbot-v1 locations')
        rows = []
        for node in data.get('nodes', [])[:60]:
            if not NODE.fullmatch(str(node.get('id', ''))):
                continue
            label = ('✅ ' if node.get('selected') else '') + str(node.get('name', 'Локация'))[:100]
            rows.append([self.button(uid, rid, label, 'select', node['id'])])
        rows.append([self.button(uid, rid, '⚡ Автовыбор', 'auto')])
        rows.append([self.button(uid, rid, '← Статус', 'status')])
        self.send(uid, self.config['routers'][rid]['name'] + ' · Выберите локацию:', rows)

    def switch(self, uid, rid, action, target, update_id):
        job_id = None
        try:
            self.authorize(uid, rid)
            command = 'xtlsbot-v1 auto'
            if action == 'select':
                if not NODE.fullmatch(target):
                    raise SafeError('Недопустимая локация.')
                command = 'xtlsbot-v1 select ' + target
            receipt = self.bridge.call(self.config['routers'][rid], command)
            job_id = receipt.get('job', {}).get('id', '')
            if receipt.get('accepted') is not True or not JOB.fullmatch(job_id):
                raise SafeError('Роутер не подтвердил приём задания.')
            self.store.finish(update_id, 'running', job_id)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                self.authorize(uid, rid)
                job = self.bridge.call(self.config['routers'][rid], 'xtlsbot-v1 job ' + job_id).get('job', {})
                if job.get('id') != job_id:
                    raise SafeError('Задание заменено другой операцией. Проверьте статус.')
                if job.get('state') == 'done':
                    self.store.finish(update_id, 'done', job_id)
                    LOG.info('operation done update=%s router=%s action=%s', update_id, rid, action)
                    self.send(uid, 'Роутер подтвердил применение настройки.')
                    self.status(uid, rid)
                    return
                if job.get('state') not in ('pending', 'running'):
                    raise SafeError('Применить настройку не удалось. Проверьте статус роутера.')
                time.sleep(2)
            raise SafeError('Истекло время ожидания задания. Результат не подтверждён; проверьте статус.')
        except SafeError as exc:
            self.store.finish(update_id, 'unconfirmed', job_id)
            self.send(uid, str(exc))
        except Exception:
            self.store.finish(update_id, 'unconfirmed', job_id)
            LOG.error('operation internal error update=%s router=%s', update_id, rid)
            self.send(uid, 'Результат операции не подтверждён. Проверьте статус.')
        finally:
            self.locks[rid].release()

    def handle(self, update):
        callback = update.get('callback_query')
        message = callback.get('message', {}) if callback else update.get('message', {})
        uid = (callback or message).get('from', {}).get('id')
        chat = message.get('chat', {})
        if chat.get('type') != 'private' or chat.get('id') != uid or uid != self.config['admin_id']:
            if callback:
                self.tg.call('answerCallbackQuery', callback_query_id=callback['id'], text='Доступ запрещён.')
            return
        self.authorize(uid)
        try:
            if not callback:
                self.menu(uid)
                return
            self.tg.call('answerCallbackQuery', callback_query_id=callback['id'])
            button = self.store.take_button(callback.get('data'), uid)
            rid, action, target = button['router'], button['action'], button['target']
            self.authorize(uid, rid)
            if action == 'status':
                self.status(uid, rid)
            elif action == 'locations':
                self.locations(uid, rid)
            elif action in ('select', 'auto'):
                if not self.locks[rid].acquire(blocking=False):
                    raise SafeError('Операция уже выполняется. Дождитесь результата.')
                if not self.store.begin(update['update_id'], uid, rid, action, target):
                    self.locks[rid].release()
                    return
                try:
                    self.send(uid, 'Запрос принят. Ожидаем подтверждение роутера…')
                    self.pool.submit(self.switch, uid, rid, action, target, update['update_id'])
                except Exception:
                    self.store.finish(update['update_id'], 'interrupted')
                    self.locks[rid].release()
                    raise
            else:
                raise SafeError('Недопустимая операция.')
        except SafeError as exc:
            self.send(uid, str(exc))

    def run(self):
        me = self.tg.call('getMe')
        if me.get('username', '').lower() != self.config['bot_username']:
            raise SafeError('Токен принадлежит другому боту.')
        if self.tg.call('getWebhookInfo').get('url'):
            raise SafeError('У бота настроен webhook. Автоматически отключать его запрещено.')
        LOG.info('pilot started routers=%d', len(self.config['routers']))
        while True:
            try:
                updates = self.tg.call('getUpdates', offset=self.store.offset(), timeout=25,
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
