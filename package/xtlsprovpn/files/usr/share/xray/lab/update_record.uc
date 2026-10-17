#!/usr/bin/ucode
let fs = require('fs');
import { operation_error } from './operation_error.mjs';

if (ARGV[0] == 'check') exit(0);

let action = ARGV[0], kind = ARGV[1];
if (index(['subscription', 'routing'], kind) < 0)
    die('Invalid update kind');

let root = '/var/run/xray-lab-control';
let path = root + '/update-' + kind + '.json';
let data = {};
try { data = json(fs.readfile(path) || '{}'); } catch (e) {}

function uptime() {
    return int(split(fs.readfile('/proc/uptime') || '0', ' ')[0]);
}

if (action == 'start') {
    data = {
        state: 'running',
        pid: int(ARGV[2]),
        last_attempt: time(),
        last_success: data.last_success || null,
        started_uptime: uptime(),
        finished: null,
        duration: null,
        code: null,
        result: null,
        error: null
    };
} else if (action == 'finish') {
    let rc = int(ARGV[2]);
    let text = fs.readfile(root + '/update-' + kind + '.tail') || '';
    let download = match(text,
        /Subscription download failed: curl=([0-9]+), HTTP=([0-9]+)/);

    data.state = rc == 0 ? 'success' : 'error';
    data.finished = time();
    data.duration = max(0, uptime() - int(data.started_uptime));
    data.code = rc;
    data.result = rc == 0 ?
        (index(text, 'Catalogue unchanged; running core retained') >= 0 ||
         index(text, 'Routing unchanged; running core retained') >= 0 ?
            'unchanged' : 'success') : 'error';

    // Only a short structured error is exposed to the UI.
    data.error = rc == 0 ? null :
        download ?
            'Загрузка подписки: curl=' + download[1] +
            ', HTTP=' + download[2] :
            'Команда завершилась с кодом ' + rc;

    if (rc != 0 && index(text,'allowInsecure')>=0)
        data.error='Конфигурация отклонена: устаревший TLS allowInsecure. Рабочие настройки сохранены.';
    if (rc != 0) data.error=operation_error(text,data.error);
    if (rc == 0) data.last_success = data.finished;
    data.pid = null;
} else {
    die('Invalid record action');
}

if (!fs.writefile(path + '.new', sprintf('%J\n', data)))
    die('Cannot write update state');
fs.chmod(path + '.new', 0600);
if (!fs.rename(path + '.new', path))
    die('Cannot commit update state');
