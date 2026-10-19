'use strict';
'require baseclass';
'require rpc';
'require poll';
const status=rpc.declare({object:'xray_lab_rescue',method:'status'});
const action=rpc.declare({object:'xray_lab_rescue',method:'action',
    params:['action','host','port','user','remote_port','local_port','host_key']});
return baseclass.extend({render:function(){return status().then(function(initial){
    if(initial.error)throw new Error(initial.error);
    const fields={};
    for(const name of ['host','port','user','remote_port','local_port','host_key'])
        fields[name]=E('input',{type:'text',value:initial[name] || '',autocomplete:'off','aria-label':name});
    const message=E('p',{role:'status'}),summary=E('p',{role:'status'});
    const pub=E('textarea',{readonly:'readonly',rows:3,style:'width:100%','aria-label':'Публичный ключ роутера'});
    const buttons={};let busy=false;
    const reasons={disabled:'выключен',paused:'пауза на 30 минут',standby:'ожидание отказа NetBird',
        waiting:'подтверждение отказа NetBird',starting:'запуск',start_failed:'ошибка запуска',
        manual:'открыт вручную на 30 минут',active:'аварийный туннель запущен',closing:'закрытие после восстановления',
        retry_wait:'пауза перед повторным запуском',connect_timeout:'истекло время установки соединения'};
    function refresh(d){
        if(d.error)throw new Error(d.error);
        pub.value=d.public_key || '';
        summary.textContent='Резерв: '+(reasons[d.state?.reason] || (d.enabled?'ожидание проверки':'выключен'))+
            (d.process?.pid?' · PID '+d.process.pid+' · RAM '+(d.process.rss_bytes/1048576).toFixed(1)+' МиБ':'')+
            (d.state?.error?' · '+d.state.error:'');
        // A live process/TCP socket alone does not prove successful administrator login.
    }
    function run(name){
        if(busy)return;busy=true;
        Object.values(buttons).forEach(b=>b.disabled=true);Object.values(fields).forEach(f=>f.disabled=true);
        message.textContent='Выполняется…';
        return action(name,...['host','port','user','remote_port','local_port','host_key'].map(k=>fields[k].value.trim()))
            .then(r=>{if(!r.ok)throw new Error(r.error || 'Операция не выполнена');message.textContent='Готово.';return status();})
            .then(refresh).catch(e=>message.textContent=e.message || String(e))
            .finally(()=>{busy=false;Object.values(buttons).forEach(b=>b.disabled=false);Object.values(fields).forEach(f=>f.disabled=false);});
    }
    for(const [name,label] of Object.entries({generate:'Создать / показать ключ',configure:'Сохранить и включить резерв',
        open:'Открыть на 30 минут',close:'Закрыть и приостановить на 30 минут',disable:'Выключить резерв'}))
        buttons[name]=E('button',{type:'button','class':'cbi-button',click:()=>run(name)},label);
    function row(label,name,desc){return E('div',{'class':'cbi-value'},[E('label',{'class':'cbi-value-title'},label),
        E('div',{'class':'cbi-value-field'},[fields[name],E('p',{},desc || '')])]);}
    refresh(initial);
    poll.add(()=>busy?Promise.resolve():status().then(refresh).catch(e=>summary.textContent='Статус резерва недоступен: '+e.message),15);
    return E('div',{'class':'cbi-map'},[E('h3',{},'Аварийный обратный SSH'),
        E('p',{},'После 5 минут отказа NetBird роутер открывает обратный SSH на ваш сервер. После восстановления резерв закрывается через 10 минут. Сохранение настроек закрывает текущий аварийный туннель.'),
        summary,row('IPv4 сервера','host'),row('SSH-порт сервера','port'),row('Пользователь туннеля','user','Отдельный пользователь без root-доступа.'),
        row('Локальный порт на сервере','remote_port','Для каждого роутера нужен отдельный порт, доступный только на 127.0.0.1 сервера.'),
        row('SSH-порт самого роутера','local_port','Укажите фактический порт Dropbear: например, 22 или 222.'),
        row('Публичный ключ сервера','host_key','Полная строка ssh-ed25519, полученная через доверенный доступ. Не приватный ключ.'),
        E('p',{},'Публичный ключ этого роутера для authorized_keys сервера:'),pub,
        E('div',{style:'display:flex;flex-wrap:wrap;gap:8px'},Object.values(buttons)),message,
        E('p',{},'Приватный ключ создаётся на роутере и не передаётся в браузер. Нужен dbclient. IPv4 и прямой маршрут через основной uplink; перехват OUTPUT в этой версии не поддерживается. Состояние процесса не заменяет проверку реального SSH-входа.')]);
}).catch(e=>E('p',{'class':'alert-message warning'},'Аварийный SSH: '+(e.message || String(e))));}});
