'use strict';
'require baseclass';
'require rpc';

const getSchedule = rpc.declare({
    object: 'xray_lab_schedule',
    method: 'get'
});

const saveSchedule = rpc.declare({
    object: 'xray_lab_schedule',
    method: 'save',
    params: [
        'subscription_enabled', 'subscription_hours',
        'routing_enabled', 'routing_hours', 'routing_minute'
    ]
});

return baseclass.extend({
    render: function() {
        return getSchedule().then(function(data) {
            if (data.error)
                throw new Error(data.error);

            function interval(value) {
                return E('select', {
                    'class': 'cbi-input-select',
                    'aria-label': 'Интервал обновления'
                }, [1, 3, 6, 12, 24].map(function(hours) {
                    return E('option', {
                        value: String(hours),
                        selected: String(hours) === String(value) ? true : null
                    }, hours === 1 ? 'Каждый час' : 'Каждые ' + hours + ' ч');
                }));
            }

            const subEnabled = E('input', {
                type: 'checkbox',
                checked: data.subscription_enabled === '1' ? true : null
            });
            const routeEnabled = E('input', {
                type: 'checkbox',
                checked: data.routing_enabled === '1' ? true : null
            });
            const subHours = interval(data.subscription_hours);
            const routeHours = interval(data.routing_hours);
            const minute = E('input', {
                type: 'number', min: '0', max: '59', step: '1',
                value: data.routing_minute,
                'class': 'cbi-input-text',
                style: 'width:5.5em',
                'aria-label': 'Минута запуска маршрутизации'
            });
            const message = E('p', {
                role: 'status',
                'aria-live': 'polite',
                style: 'margin:10px 0 0'
            });

            function row(title, enabled, controls) {
                return E('div', {
                    style: 'display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:10px 0;border-bottom:1px solid var(--border-color-medium,#ddd)'
                }, [
                    E('label', {
                        style: 'display:flex;align-items:center;gap:8px;min-width:170px;margin:0'
                    }, [enabled, E('strong', {}, title)]),
                    ...controls
                ]);
            }

            const button = E('button', {
                type: 'button',
                'class': 'cbi-button cbi-button-apply',
                style: 'margin-top:14px',
                click: function() {
                    if (!minute.checkValidity() ||
                        !/^[0-9]{1,2}$/.test(minute.value)) {
                        message.style.color = '#c0392b';
                        message.textContent = 'Укажите минуту от 0 до 59.';
                        return;
                    }

                    button.disabled = true;
                    message.style.color = '';
                    message.textContent = 'Сохраняем расписание…';

                    saveSchedule(
                        subEnabled.checked ? '1' : '0',
                        subHours.value,
                        routeEnabled.checked ? '1' : '0',
                        routeHours.value,
                        minute.value
                    ).then(function(result) {
                        if (!result.ok)
                            throw new Error(result.error || 'Ошибка сохранения');
                        message.style.color = '#218739';
                        message.textContent = result.message;
                    }).catch(function(error) {
                        message.style.color = '#c0392b';
                        message.textContent = error.message || String(error);
                    }).finally(function() {
                        button.disabled = false;
                    });
                }
            }, 'Сохранить расписание');

            return E('div', {'class': 'cbi-map'}, [
                E('h2', {}, 'Автообновление'),
                E('p', {}, 'Расписание использует время роутера. При интервале 6 часов подписка обновляется в 00:00, 06:00, 12:00 и 18:00. Маршрутизация — в указанную минуту этих часов.'),
                row('Подписка', subEnabled, [subHours]),
                row('Маршрутизация', routeEnabled, [
                    routeHours, E('span', {}, 'на минуте'), minute
                ]),
                button,
                message,
                E('p', {style: 'margin-top:10px;opacity:.75'},
                    'Сохраняется отдельно от остальных настроек. Тоннель продолжает работать.')
            ]);
        }).catch(function(error) {
            return E('div', {'class': 'alert-message warning'},
                'Не удалось загрузить расписание: ' +
                (error.message || String(error)));
        });
    }
});
