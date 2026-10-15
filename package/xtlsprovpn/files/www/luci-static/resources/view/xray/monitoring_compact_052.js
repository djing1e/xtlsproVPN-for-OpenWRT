'use strict';
'require view';
'require poll';
'require view.xray.lab_052 as lab';

function fileDate(tag){return /^\d{12}$/.test(tag || '')?tag.slice(6,8)+'.'+tag.slice(4,6)+'.'+tag.slice(0,4):'Нет данных';}
function row(label,value,detail) {
    return E('div',{'class':'xt-monitor-row'},[
        E('dt',{},label),E('dd',{},[E('strong',{},String(value ?? '—')),detail?E('small',{},detail):null].filter(Boolean))
    ]);
}
function group(title,rows) {return E('section',{'class':'fx-card xt-monitor-group'},[E('h3',{},title),E('dl',{},rows)]);}
function update(title,item,fallback) {
    const labels={running:'Выполняется…',success:'Успешно',error:'Ошибка',interrupted:'Прервано'};
    const status=item?.state==='success' && item.result==='unchanged'?'Без изменений':labels[item?.state] || 'Запусков ещё нет';
    return group(title,[row('Результат',status,item?.error),
        row('Последняя попытка',lab.date(item?.last_attempt)),
        row('Успешное обновление',lab.date(item?.last_success || fallback)),
        row('Длительность',item?.state==='running'?'Выполняется':item?.duration!=null?item.duration+' с':'—')]);
}
return view.extend({
    load:()=>lab.status(),
    render:function(initial) {
        const body=E('div',{'class':'xt-monitor'});
        function draw(s) {
            const w=s.watchdog || {},h=s.health;
            body.replaceChildren(
                group('Состояние',[
                    row('Прокси',s.core?.running?'Работает':'Остановлен',s.core?.running?'PID '+s.core.pid:null),
                    row('Интерфейс',s.interface.name+' / '+s.interface.device,s.interface.up?'Поднят':'Выключен'),
                    row('HTTPS через прокси',h?(h.proxy_ok?'OK':'Ошибка'):'Ожидание проверки',h?lab.date(h.checked):'Проверка каждые 60 секунд'),
                    row('Память процесса',lab.bytes(s.core?.rss || 0)),
                    row('Маршрутизация',s.routing?.profile==='roscomvpn'?'Раздельная':'Через прокси'),
                    row('Профиль источника',lab.date(s.routing?.upstream)),
                    row('GeoIP · версия Git',fileDate(s.routing?.geoip_version),s.routing?.geoip_version),
                    row('GeoSite · версия Git',fileDate(s.routing?.geosite_version),s.routing?.geosite_version)
                ]),
                group('Восстановление',[
                    row('Watchdog',w.enabled?'Включён':'Выключен',lab.reason(w.reason)),
                    row('Проверка',lab.date(w.checked)),
                    row('Перезапуски за 10 минут',(w.restarts || []).length,'Лимит: 3; пауза между перезапусками: 90 с'),
                    row('Потери доступности',w.outages || 0,'За время работы монитора'),
                    row('Последнее восстановление',lab.date(w.recovery_at),w.last_outage_seconds!=null?'Недоступность: '+w.last_outage_seconds+' с':null)
                ]),
                update('Подписка',s.updates?.subscription,s.subscription?.updated),
                update('Проверка списков',s.updates?.routing,s.routing?.updated),
                E('details',{'class':'xt-monitor-help'},[
                    E('summary',{},'Как работает мониторинг'),
                    E('p',{},'Интерфейс проверяется каждые 15 секунд. После изменения сети монитор выдерживает заданную задержку. Ошибки процесса и перехвата подтверждаются тремя проверками; ошибки HTTPS — при доступном прямом соединении.'),
                    E('p',{},'История попыток обновления и счётчики монитора хранятся в RAM до перезагрузки. Последнее успешное обновление может отображаться из сохранённых данных.'),
                    E('a',{href:L.url('admin/services/forkop-xray/settings')},'Открыть настройки')
                ])
            );
        }
        draw(initial);poll.add(()=>lab.status().then(draw),5);
        return E('div',{},[lab.style(),E('style',{},
            '.xt-monitor{max-width:1100px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;align-items:stretch}.xt-monitor-group{padding:16px!important}.xt-monitor-group h3{margin:0 0 12px}.xt-monitor-group dl{margin:0}.xt-monitor-row{display:grid;grid-template-columns:minmax(120px,1fr) minmax(0,1.2fr);gap:12px;padding:9px 0;border-top:1px solid #8883}.xt-monitor-row dt{opacity:.75}.xt-monitor-row dd{margin:0;overflow-wrap:anywhere}.xt-monitor-row strong{font-weight:500}.xt-monitor-row small{display:block;opacity:.65;margin-top:3px;line-height:1.4}.xt-monitor-help{grid-column:1/-1}.xt-monitor-help summary{cursor:pointer}@media(max-width:760px){.xt-monitor{grid-template-columns:1fr}}'),E('h2',{},'xtlsproVPN'),body]);
    },handleSaveApply:null,handleSave:null,handleReset:null
});
