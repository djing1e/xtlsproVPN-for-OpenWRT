'use strict';
'require baseclass';
'require rpc';
'require poll';

const getStatus = rpc.declare({object: 'xray_lab_netbird', method: 'status'});
const runAction = rpc.declare({
    object: 'xray_lab_netbird', method: 'action',
    params: ['action', 'management_url', 'hostname', 'setup_key']
});

return baseclass.extend({
    render: function() {
        return getStatus().then(function(initial) {
            if (initial.error) throw new Error(initial.error);
            let submitting = false, current = initial;
            const url = E('input', {
                type: 'url', 'class': 'cbi-input-text',
                placeholder: 'https://netbird.example.com',
                value: initial.management_url || '',
                autocomplete: 'off', 'aria-label': 'Сервер управления NetBird'
            });
            const hostname = E('input', {
                type: 'text', 'class': 'cbi-input-text',
                placeholder: 'router-001', value: initial.hostname || '',
                maxlength: '63', autocomplete: 'off', 'aria-label': 'Имя устройства'
            });
            const key = E('input', {
                type: 'password', 'class': 'cbi-input-text',
                autocomplete: 'new-password', 'aria-label': 'Setup key NetBird'
            });
            const summary = E('p', {role: 'status', 'aria-live': 'polite'});
            const message = E('p', {role: 'status', 'aria-live': 'polite'});
            const resources = E('p', {style: 'opacity:.75'});
            const versions = E('p', {role: 'status'});
            const guard = E('p', {role: 'status'});
            const buttons = {};

            function refresh(data) {
                if (data.error) throw new Error(data.error);
                current = data;
                const busy = submitting || ['pending', 'running'].includes(data.job.state);
                summary.textContent = !data.installed ? 'NetBird не установлен.' :
                    data.connected ? 'Подключён · ' + data.netbird_ip + (data.version ? ' · ' + data.version : '') :
                    'NetBird установлен, соединение с сервером управления не установлено.';
                summary.style.color = data.connected ? '#00b991' : '';
                const pkg=data.package || {};
                versions.textContent='Пакет OpenWrt: '+(pkg.installed || 'не определён')+
                    (pkg.available ? ' · В репозитории: '+pkg.available+(pkg.update_available?' · доступно обновление':' · обновление не требуется') : ' · нажмите «Проверить обновления»');
                message.textContent = data.job.message || '';
                message.style.color = data.job.state === 'failed' ? '#c0392b' : '';
                const reasons = {
                    healthy: 'соединение исправно', startup_grace: 'ожидание после запуска',
                    settling: 'ожидание после восстановления', confirming_failure: 'подтверждение сбоя',
                    waiting_uplink: 'ожидание доступа в интернет', management_unavailable: 'сервер управления недоступен',
                    manual_down: 'подключение остановлено вручную', authentication_required: 'нужна повторная авторизация',
                    paused: 'наблюдение приостановлено', recovering: 'восстановление службы',
                    cooldown: 'пауза перед повторной попыткой', rate_limited: 'достигнут лимит попыток за час',
                    not_checked: 'проверка ещё не выполнена'
                };
                guard.textContent = !data.installed ? '' : 'Guard: ' +
                    (!data.enabled ? reasons.paused : reasons[data.guard?.reason] || reasons.not_checked) +
                    ' · попыток за час: ' + (data.guard?.attempts?.length || 0);
                resources.textContent = data.installed ?
                    'Бинарник: ' + (data.resources.binary_bytes / 1048576).toFixed(1) + ' МиБ · RAM процесса: ' +
                    (data.resources.rss_bytes / 1048576).toFixed(1) + ' МиБ · Автозапуск: ' +
                    (data.enabled ? 'включён' : 'выключен') : '';
                buttons.install.disabled = busy || data.installed;
                buttons.check_update.disabled = busy || !data.installed;
                buttons.update.disabled = busy || !data.installed || !data.package?.update_available;
                buttons.connect.disabled = busy || !data.installed;
                buttons.disconnect.disabled = busy || !data.installed;
                url.disabled = hostname.disabled = key.disabled = busy;
            }
            function action(name) {
                if (submitting) return;
                if (name === 'connect' && (!url.value.trim() || !url.checkValidity())) {
                    message.textContent = 'Укажите HTTPS-адрес сервера управления.';
                    return;
                }
                const secret = key.value.trim();
                const endpoint = value => (value || '').replace(/\/$/, '').replace(/:443$/, '');
                const registeredHere = current.registered &&
                    endpoint(url.value.trim()) === endpoint(current.management_url || current.active_management_url);
                if (name === 'connect' && !secret && !registeredHere) {
                    message.textContent = 'Для первой регистрации на этом сервере заполните Setup key.';
                    message.style.color = '#c0392b';
                    key.focus();
                    return;
                }
                submitting = true;
                key.value = '';
                refresh(current);
                message.textContent = 'Запускаем операцию NetBird…';
                runAction(name, url.value.trim(), hostname.value.trim(), secret).then(function(result) {
                    if (!result.ok) throw new Error(result.error || 'Операция не запущена');
                    return getStatus();
                }).then(function(data) {
                    submitting = false;
                    refresh(data);
                }).catch(function(error) {
                    submitting = false;
                    refresh(current);
                    message.textContent = error.message || String(error);
                    message.style.color = '#c0392b';
                });
            }
            ['install', 'connect', 'disconnect', 'check_update', 'update'].forEach(function(name) {
                buttons[name] = E('button', {
                    type: 'button', 'class': 'cbi-button ' + (name === 'connect' ? 'cbi-button-apply' : 'cbi-button-action'),
                    click: function() { action(name); }
                }, {install: 'Установить NetBird', connect: 'Подключить / применить', disconnect: 'Отключить', check_update: 'Проверить обновления', update: 'Обновить NetBird'}[name]);
            });
            function row(label, input, description) {
                return E('div', {'class': 'cbi-value'}, [
                    E('label', {'class': 'cbi-value-title'}, label),
                    E('div', {'class': 'cbi-value-field'}, [input,
                        E('div', {'class': 'cbi-value-description'}, description)])
                ]);
            }
            refresh(initial);
            poll.add(function() {
                return getStatus().then(refresh).catch(function(error) {
                    summary.style.color = '';
                    summary.textContent = 'Статус NetBird недоступен: ' + (error.message || String(error));
                });
            }, 10);
            return E('div', {'class': 'cbi-map'}, [
                E('h2', {}, 'Административный доступ · NetBird'),
                E('p', {}, 'Постоянное подключение к вашему self-hosted серверу. После настройки запускается автоматически, независимо от службы Xray.'),
                summary, resources, versions, guard,
                row('Сервер управления', url, 'HTTPS-адрес вашего NetBird Management Server.'),
                row('Имя устройства', hostname, 'Латинские буквы, цифры и дефис. Можно оставить пустым.'),
                row('Setup key', key, 'Для регистрации устройства. При повторном подключении зарегистрированного устройства можно оставить пустым. В настройках xtlsproVPN ключ не сохраняется.'),
                E('div', {style: 'display:flex;flex-wrap:wrap;gap:8px;margin-top:14px'},
                    [buttons.install, buttons.connect, buttons.disconnect, buttons.check_update, buttons.update]),
                message,
                E('p', {style: 'opacity:.8'}, 'NetBird обновляется отдельно из подписанного репозитория OpenWrt. На время обновления административное соединение может прерваться; регистрация сохраняется. Новая версия upstream появится здесь после её включения в репозиторий OpenWrt.'),
                E('p', {style: 'margin-top:12px;opacity:.8'}, 'В новой зоне firewall открываются только TCP 22, 80 и 443 к самому роутеру. Существующая зона wt0 сохраняется. Доступ к домашней сети не добавляется. NetBird не управляет DNS и маршрутами подсетей.'),
                E('p', {style: 'opacity:.8'}, 'Используются обычные SSH и LuCI с их авторизацией. Группы администраторов и правила доступа настройте на сервере NetBird.')
            ]);
        }).catch(function(error) {
            return E('div', {'class': 'alert-message warning'}, 'Не удалось загрузить NetBird: ' + (error.message || String(error)));
        });
    }
});
