'use strict';
'require baseclass';
'require rpc';
'require ui';

const methods = {};
['status','diagnostics','logs','job'].forEach(method => methods[method] = rpc.declare({object:'xray_lab',method,expect:{}}));
const action = rpc.declare({object:'xray_lab',method:'action',params:['action','location'],expect:{}});
const reasons = {
    healthy:'Проверки проходят',paused:'Приостановлен',interface_down:'Интерфейс выключен — ожидаем сеть',
    settling:'Ожидаем стабилизацию интерфейса',operation_running:'Операция выполняется',
    confirming_failure:'Подтверждаем сбой',uplink_unavailable:'Нет прямой доступности — ожидаем сеть / DNS',
    restart_limit:'Достигнут лимит перезапусков: нужна диагностика',cooldown:'Пауза между перезапусками',
    interface_recovered:'Восстановление после изменения интерфейса',local_integration_failed:'Восстановление перехвата LAN',
    proxy_failed:'Восстановление после ошибок прокси',not_started:'Монитор ещё не запущен'
};

const operationNames={start:'Запуск прокси',stop:'Остановка прокси',restart:'Перезапуск прокси',sync:'Обновление подписки',select:'Выбор локации',latency:'Измерение задержек',diagnose:'Диагностика',recover:'Восстановление прокси'};
const completedNames={start:'Прокси запущен',stop:'Прокси остановлен',restart:'Прокси перезапущен',sync:'Подписка обновлена',select:'Локация применена',latency:'Замеры задержек завершены',diagnose:'Диагностика завершена',recover:'Прокси восстановлен'};
let toastRoot, activeNotice, pending=false;
function toast(title,detail,tone,persistent) {
    if(!toastRoot || !toastRoot.isConnected){toastRoot=E('div',{'class':'fx-toasts','aria-live':'polite'});document.body.appendChild(toastRoot);}
    const node=E('div',{'class':'fx-toast fx-toast-'+tone,role:tone==='error'?'alert':'status'},[
        E('div',{},[E('strong',{},title),E('p',{},detail || '')]),
        E('button',{type:'button','class':'fx-toast-close','aria-label':'Закрыть уведомление',click:()=>node.remove()},'×')
    ]);
    toastRoot.appendChild(node);
    while(toastRoot.children.length>4)toastRoot.firstChild.remove();
    if(!persistent)setTimeout(()=>node.remove(),tone==='error'?12000:6500);
    return node;
}
function observe(s) {
    const j=s.job || {};
    if(activeNotice && j.id===activeNotice.id && ['done','failed'].includes(j.state)) {
        activeNotice.node.remove();
        let title=j.state==='done'?(completedNames[j.action] || 'Готово'):'Операция не выполнена';
        let detail=j.state==='failed'?j.message:activeNotice.detail,tone=j.state==='done'?'success':'error';
        if(j.state==='done' && j.action==='select' && activeNotice.location==='auto')title='Автовыбор включён';
        const summary=s.diagnostics_summary;
        if(j.state==='done' && j.action==='diagnose' && summary?.job_id===j.id){
            detail='Ошибок: '+summary.errors+' · требуют внимания: '+summary.pending;
            tone=summary.errors?'error':summary.pending?'warn':'success';
        }
        toast(title,detail,tone);
        activeNotice=null;pending=false;
    }
    return s;
}
function request(op,location,label,element) {
    if(pending)return Promise.resolve();
    pending=true;if(element)element.disabled=true;
    const detail=label || (op==='select' && location==='auto'?'Включение leastPing':'');
    const note=toast(operationNames[op] || 'Операция',detail || 'Ожидаем результат…','working',true);
    return action(op,location || '').then(r=>{
        if(r.error)throw new Error(r.error);
        activeNotice={id:r.id,node:note,detail,location};
        return methods.status().then(observe).catch(()=>{});
    }).catch(e=>{note.remove();pending=false;activeNotice=null;toast('Операция не выполнена',e.message,'error');if(element)element.disabled=false;});
}

return baseclass.extend({
    status:()=>methods.status().then(observe), diagnostics:methods.diagnostics, logs:methods.logs, job:methods.job,
    busy:s=>pending || s.operation_busy || ['pending','running'].includes((s.job || {}).state),
    reason:s=>reasons[s] || s || 'Нет данных',
    bytes:function(value) {
        let v=Number(value)||0, units=['Б','КиБ','МиБ','ГиБ'], n=0;
        while(v>=1024 && n<units.length-1){v/=1024;n++;}
        return v.toFixed(n?1:0)+' '+units[n];
    },
    date:value=>value ? new Date(value*1000).toLocaleString() : 'Нет данных',
    when:value=>value ? new Date(value*1000).toLocaleTimeString() : 'Ещё не проверено',
    nav:function(current) {
        const tabs=[['dashboard','Дашборд'],['settings','Настройки'],['diagnostics','Диагностика'],['monitoring','Мониторинг']];
        return E('ul',{'class':'cbi-tabmenu'},tabs.map(t=>E('li',{'class':t[0]===current?'cbi-tab':'cbi-tab-disabled'},
            E('a',{href:L.url('admin/services/forkop-xray/'+t[0])},t[1]))));
    },
    style:function(){return E('style',{},
        '.fx-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px;margin:12px 0}' +
        '.fx-card{border:1px solid #6666;border-radius:4px;padding:12px;background:transparent;min-width:0}' +
        '.fx-card h4{margin:0 0 12px}.fx-card p{margin:6px 0}.fx-card.selected{border:2px solid #00a878}' +
        '.fx-nodes{grid-template-columns:repeat(auto-fill,minmax(150px,180px));gap:8px;align-items:stretch;justify-content:start}.fx-location{padding:9px}.fx-location h4{font-size:13px;margin:0 0 7px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fx-location p{margin:4px 0}.fx-location .cbi-button{margin-top:5px;padding:3px 8px;font-size:12px}.fx-location-meta{display:flex;justify-content:space-between;gap:6px;font-size:12px}.fx-service-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.fx-facts{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 12px;margin:0}.fx-facts dt{opacity:.75}.fx-facts dd{margin:0;overflow-wrap:anywhere}.fx-diagnostics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;align-items:start}.fx-diag-card{padding:10px}.fx-diag-card h4{margin-bottom:8px;font-size:13px}.fx-diag-card .fx-check{margin:6px 0}.fx-diag-card strong{font-size:12px}.fx-diag-card .fx-muted{font-size:12px;overflow-wrap:anywhere}.fx-border-ok{border-color:#00a878}.fx-border-warn{border-color:#c7a936}.fx-border-error{border-color:#e45c55}' +
        '.fx-ok{color:#00a878}.fx-error{color:#e45c55}.fx-warn{color:#c7a936}.fx-value{font-size:1.35em;margin-top:8px}' +
        '.fx-buttons{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.fx-two{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:10px;align-items:start}' +
        '.fx-card button{white-space:normal}.fx-muted{opacity:.75;font-size:.9em}.fx-check{margin:9px 0}' +
        '.fx-location{display:grid;grid-template-columns:24px minmax(0,1fr);gap:8px 10px;align-items:center;text-align:left;padding:14px 12px;min-height:84px;border:1px solid #8885;border-radius:9px;background:transparent;color:inherit;font:inherit;cursor:pointer;transition:background .15s,border-color .15s,transform .15s;box-sizing:border-box}.fx-location:not(:disabled):hover{background:#168ab110;border-color:#22a7b8;transform:translateY(-1px)}.fx-location:focus-visible{outline:2px solid #22a7b8;outline-offset:3px}.fx-location.selected{border-color:#00b991;background:#00b99112;box-shadow:inset 0 0 0 1px #00b991}.fx-location:disabled{cursor:default;opacity:1}.fx-location-name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fx-location-ping{grid-column:2;font-size:13px;color:#00b991}.fx-location-unavailable .fx-location-ping{color:#df7368}.fx-location-unknown .fx-location-ping{color:inherit;opacity:.65}.fx-flag{display:inline-block;width:22px;height:14px;border-radius:2px;box-shadow:0 0 0 1px #8883}.fx-flag-fi{background:linear-gradient(90deg,transparent 28%,#003580 28% 45%,transparent 45%),linear-gradient(transparent 38%,#003580 38% 62%,transparent 62%),#fff}.fx-flag-de{background:linear-gradient(#171717 33%,#d33 33% 66%,#ffce00 66%)}.fx-flag-nl{background:linear-gradient(#ae1c28 33%,#fff 33% 66%,#21468b 66%)}.fx-flag-ee{background:linear-gradient(#4891d9 33%,#171717 33% 66%,#fff 66%)}.fx-flag-ch{background:linear-gradient(#fff,#fff) center/3px 10px no-repeat,linear-gradient(#fff,#fff) center/10px 3px no-repeat,#df2028}.fx-flag-empty,.fx-flag-emoji{box-shadow:none;height:auto;line-height:14px;text-align:center;color:#22a7b8}.fx-diagnostics{align-items:stretch}.fx-diag-card{border-radius:8px;display:flex;flex-direction:column}.fx-diag-card h4{display:flex;justify-content:space-between;gap:8px}.fx-diag-card .fx-check{padding:5px 0;border-bottom:1px solid #8882}.fx-diag-card .fx-check:last-child{border-bottom:0}.fx-border-working{border-color:#22a7b8;background:#22a7b808}.fx-border-waiting{border-color:#8884}.fx-working{color:#22a7b8}.fx-waiting{opacity:.65}.fx-stage-label{font-weight:400;font-size:11px;white-space:nowrap}.fx-progress{border:1px solid #8884;border-radius:8px;padding:12px;margin:10px 0 14px}.fx-progress-line{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px}.fx-progress-track{height:5px;background:#8883;border-radius:3px;overflow:hidden}.fx-progress-fill{height:100%;background:#22a7b8;transition:width .3s}.fx-toasts{position:fixed;right:22px;bottom:22px;z-index:10000;display:grid;gap:8px;width:min(390px,calc(100vw - 32px));pointer-events:none}.fx-toast{display:flex;justify-content:space-between;gap:12px;padding:13px 15px;border-radius:9px;border-left:4px solid #22a7b8;background:var(--background-color,#20282d);color:var(--text-color,#eee);box-shadow:0 5px 24px #0004;pointer-events:auto}.fx-toast p{margin:5px 0 0;font-size:12px;overflow-wrap:anywhere}.fx-toast-success{border-color:#00b991}.fx-toast-error{border-color:#e45c55}.fx-toast-warn{border-color:#c7a936}.fx-toast-close{align-self:flex-start;border:0;background:transparent;color:inherit;font-size:20px;cursor:pointer}' +
        '.fx-announce{margin-top:10px;padding:6px 9px;border-left:3px solid #22a7b8;background:#8881;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}.fx-diag-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin:8px 0}.fx-diagnostics{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;align-items:start}.fx-diag-card{padding:9px 10px;border-radius:6px}.fx-diag-card h4{margin:0 0 6px;font-size:12px}.fx-diag-card .fx-check{margin:0;padding:0;border:0}.fx-diag-card .fx-check summary{display:flex;align-items:center;justify-content:space-between;gap:6px;min-height:24px;padding:0;cursor:pointer;list-style:none}.fx-check summary::-webkit-details-marker{display:none}.fx-check summary:after{content:"›";opacity:.5}.fx-check[open] summary:after{transform:rotate(90deg)}.fx-diag-card .fx-check strong{font-size:12px;font-weight:500}.fx-check-detail{padding:1px 0 5px 13px;font-size:11px!important}.fx-progress{padding:8px 10px;margin:8px 0}.fx-progress-line{margin-bottom:5px;font-size:12px}@media(max-width:900px){.fx-diagnostics{grid-template-columns:repeat(2,minmax(0,1fr))}}' +
        '.fx-diagnostics{grid-template-columns:repeat(2,minmax(0,1fr))}.fx-diag-column{display:flex;flex-direction:column;gap:6px;min-width:0}.fx-check-detail{overflow-wrap:anywhere}.fx-diag-card{margin:0}' +
        '@media(max-width:1050px){.fx-two{grid-template-columns:1fr}}@media(max-width:650px){.fx-service-grid,.fx-diagnostics{grid-template-columns:1fr}.fx-nodes{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:360px){.fx-nodes{grid-template-columns:1fr}}');},
    card:function(title,value,detail,state){return E('div',{'class':'fx-card'},[
        E('h4',{},title),E('div',{'class':'fx-value '+(state?'fx-'+state:'')},value),E('p',{'class':'fx-muted'},detail || '')]);},
    request,
    toast,
    flag:function(name) {
        const m=(name || '').match(/^([\u{1F1E6}-\u{1F1FF}]{2})\s*/u);
        if(!m)return {flag:E('span',{'class':'fx-flag fx-flag-empty','aria-hidden':'true'},'◉'),name:name || 'Локация'};
        const country=Array.from(m[1]).map(c=>String.fromCharCode(c.codePointAt(0)-0x1f1e6+97)).join('');
        const known=["at", "be", "bg", "ch", "de", "dk", "ee", "fi", "fr", "gb", "hk", "hu", "id", "ie", "it", "jp", "kz", "lt", "lu", "nl", "pl", "ro", "ru", "se", "tr", "ua", "us"].includes(country);
        return {flag:known?E('img',{'class':'fx-flag',src:L.resource('view/xray/flags/'+country+'.svg'),alt:country.toUpperCase(),width:22,height:14}):E('span',{'class':'fx-flag fx-flag-empty',title:country.toUpperCase()},country.toUpperCase()),name:name.slice(m[0].length)};
    },
    location:function(name,ping,op,location,disabled,selected,detail) {
        const f=this.flag(name);
        return E('button',{type:'button','class':'fx-location'+(selected?' selected':'')+(ping==='Недоступен'?' fx-location-unavailable':ping==='Нет замера'?' fx-location-unknown':''),
            disabled:disabled?true:null,'aria-pressed':selected?'true':'false',title:detail || name,
            click:ev=>request(op,location,name,ev.currentTarget)},[
                f.flag,E('span',{'class':'fx-location-name'},f.name),E('span',{'class':'fx-location-ping'},ping)
            ]);
    },
    button:function(title,op,location,disabled) {
        return E('button',{type:'button','class':'cbi-button cbi-button-action',disabled:disabled ? true : null,
            click:ev=>request(op,location,'',ev.currentTarget)},title);
    },
    jobNote:function(s){
        const j=s.job || {};
        const labels={start:'Запуск',stop:'Остановка',restart:'Перезапуск',sync:'Обновление подписки',select:'Выбор локации',latency:'Измерение задержек',diagnose:'Диагностика',recover:'Восстановление'};
        return E('p',{'role':'status','class':j.state==='failed'?'fx-error':'fx-muted'},
            ['pending','running'].includes(j.state)?'Выполняется: '+(labels[j.action] || 'операция')+'…':j.message || (s.operation_lock_error || (s.operation_busy?'Операции заблокированы: другая операция держит блокировку.':'')));
    }
});
