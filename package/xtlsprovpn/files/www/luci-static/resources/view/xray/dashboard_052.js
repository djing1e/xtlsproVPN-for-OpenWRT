'use strict';
'require view';
'require poll';
'require view.xray.lab_148 as lab';

return view.extend({
    load:function(){return lab.status();},
    render:function(initial){
        const body=E('div');let previous;
        const draw=s=>{
            const busy=lab.busy(s), now=s.time, traffic=s.traffic || {};
            let up=0,down=0;
            if(previous && previous.pid===s.core.pid && now>previous.time){
                up=Math.max(0,traffic.upload-previous.upload)/(now-previous.time);
                down=Math.max(0,traffic.download-previous.download)/(now-previous.time);
            }
            previous={pid:s.core.pid,time:now,upload:traffic.upload,download:traffic.download};
            const health=s.health;
            const selected=(s.nodes || []).filter(n=>n.selected).map(n=>n.name).join(', ');
            const nodes=(s.nodes || []).slice().sort((a,b)=>(a.rtt_ms ?? Infinity)-(b.rtt_ms ?? Infinity));
            const nodeCard=n=>lab.location(n.name,n.alive===true?n.rtt_ms+' мс':n.alive===false?'Недоступен':'Нет замера',
                'select',n.id,busy || (s.mode==='manual' && s.location===n.id),n.selected,
                n.name+' · проверка '+lab.when(n.checked));
            const connection=s.core.running && s.enabled && s.interception.active && s.interface.up && health?.proxy_ok;
            const cards=E('div',{'class':'fx-grid'},[
                lab.card('Скорость',lab.bytes(down)+'/с ↓',lab.bytes(up)+'/с ↑'),
                lab.card('LAN через xtlsproVPN',lab.bytes((traffic.lan_upload || 0)+(traffic.lan_download || 0)),
                    'Байты на TPROXY-входах с запуска ядра'),
                lab.card('RAM xtlsproVPN',lab.bytes(s.core.rss),'Свободно системе: '+lab.bytes(s.memory.available)),
                lab.card('Соединение',s.direct_mode?'Прямой интернет':connection?'Проверка пройдена':!s.core.running?'Остановлено':'Нужна проверка',
                    s.direct_mode?'Перехват LAN отключён; прокси проверяется в фоне':health?'HTTPS через SOCKS: '+(health.proxy_ok?'OK':'ошибка')+' · '+lab.when(health.checked):'Запустите диагностику',connection?'ok':'warn')
            ]);
            const facts=items=>E('dl',{'class':'fx-facts'},items.flatMap(item=>[E('dt',{},item[0]),E('dd',{},item[1])]));
            const sub=s.subscription || {}, usage=sub.traffic;
            const expires=sub.expire ? lab.date(sub.expire)+(sub.expire<=now?' · истекла':' · '+Math.ceil((sub.expire-now)/86400)+' дн.'):'Нет данных';
            let quota='Нет данных';
            if(usage) quota=lab.bytes(usage.used)+(usage.total?' / '+lab.bytes(usage.total):usage.unlimited?' / безлимит':' / лимит не указан');
            const service=E('div',{'class':'fx-service-grid'},[
                E('div',{'class':'fx-card'},[E('h4',{},'Сервисы'),facts([
                    ['xtlsproVPN',s.direct_mode?'Прямой режим':s.core.running?'Работает':'Остановлен'],
                    ['Перехват LAN',s.enabled && s.interception.active?'Установлен':'Не активен'],
                    ['Шлюз / DNS',s.lan.address],['Watchdog',lab.reason(s.watchdog.reason)]
                ])]),
                E('div',{'class':'fx-card'},[E('h4',{},'Подписка'),facts([
                    ['Название',sub.title || 'Нет данных'],['Обновлена',lab.date(sub.updated)],
                    ['Действует до',expires],['Трафик',quota]
                ]),...(sub.announce?[E('div',{'class':'fx-announce'},sub.announce)]:[]),E('p',{'class':'fx-muted'},usage?'Трафик по данным сервера на момент обновления.':'Название, срок и трафик отображаются, если сервер передаёт их в подписке.')])
            ]);
            const current=(s.nodes || []).find(n=>n.selected);
            const auto=lab.location('Автовыбор',current?.alive===true?current.rtt_ms+' мс':'leastPing',
                'select','auto',busy || s.mode==='auto',s.mode==='auto',s.mode==='auto'?'leastPing включён':'Включить leastPing');
            const content=[cards,service,
                E('div',{'class':'fx-buttons'},[
                    lab.button('Обновить подписку и списки','sync','',busy),lab.button('Измерить задержки','latency','',busy || !s.metrics_ready),
                    lab.button(s.enabled && s.core.running?'Остановить прокси':'Запустить прокси',s.enabled && s.core.running?'stop':'start','',busy),
                    E('a',{'class':'cbi-button',href:L.url('admin/services/forkop-xray/diagnostics')},'Диагностика')
                ]),lab.jobNote(s),
                E('div',{'class':'fx-card'},[E('h4',{},'main · '+nodes.length+' локаций'),
                    E('div',{'class':'fx-grid fx-nodes'},[auto,...nodes.map(nodeCard)])]),
                E('p',{'class':'fx-muted'},s.direct_mode?'Прямой интернет. Автоматический возврат после успешных проверок HTTPS и DNS.':'Текущий профиль: внешний IPv4 TCP/UDP через прокси; локальные сети напрямую. IPv6 не проксируется.')];
            body.replaceChildren(...content);
        };
        draw(initial);poll.add(()=>lab.status().then(draw),5);
        return E('div',{},[lab.style(),E('h2',{},'xtlsproVPN'),body]);
    },
    handleSaveApply:null,handleSave:null,handleReset:null
});
