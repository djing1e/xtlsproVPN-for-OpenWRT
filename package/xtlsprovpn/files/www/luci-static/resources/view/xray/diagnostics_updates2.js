'use strict';
'require view';
'require poll';
'require ui';
'require view.xray.lab_052 as lab';

return view.extend({
    load:function(){return Promise.all([lab.status(),lab.diagnostics()]);},
    render:function(initial){
        const body=E('div'),expanded={};
        const draw=data=>{
            const s=data[0], d={...data[1],checks:(data[1].checks || []).map(c=>c.group==='client' && c.state==='pending'?{...c,state:'info'}:c)}, busy=lab.busy(s);
            const groups=[['core','xtlsproVPN'],['interface','Интерфейс и шлюз'],['firewall','Nftables и маршруты'],['dns','DNS'],['outbounds','Подключения'],['client','LAN-клиент']];
            const requested=s.job?.action==='diagnose' && ['pending','running'].includes(s.job.state);
            const fresh=d.job_id && d.job_id===s.job?.id;
            const active=requested && (d.running || !fresh);
            const interrupted=d.running && !requested;
            const preparing=active && !fresh;
            const total=d.total || 20+(s.nodes || []).length;
            const completed=preparing?0:(d.completed || 0);
            const percent=Math.min(100,Math.round(completed*100/total));
            const stage=preparing?'Подготовка':(groups.find(g=>g[0]===d.stage)?.[1] || '');
            const errors=(d.checks || []).filter(c=>c.state==='error').length;
            const warnings=(d.checks || []).filter(c=>c.state==='pending').length;
            const doneColor=errors?'#e45c55':warnings?'#c7a936':'#00b991';
            const progress=E('div',{'class':'fx-progress'},[
                E('div',{'class':'fx-progress-line'},[
                    E('strong',{'class':active?'fx-working':interrupted?'fx-error':'fx-muted'},
                        active?'Проверяем: '+stage+(d.current && !preparing?' · '+d.current:''):interrupted?'Диагностика прервана':d.checked?'Проверка завершена · ошибок: '+errors+' · требуют внимания: '+warnings:'Готово к проверке'),
                    E('span',{'class':'fx-muted'},completed+' / '+total)
                ]),E('div',{'class':'fx-progress-track',role:'progressbar','aria-label':'Прогресс диагностики',
                    'aria-valuemin':'0','aria-valuemax':'100','aria-valuenow':String(percent)},[
                    E('div',{'class':'fx-progress-fill',style:'width:'+percent+'%;'+(!active && d.checked?'background:'+doneColor:'' )})
                ])
            ]);
            const blocks=groups.map(g=>{
                const checks=(preparing?[]:d.checks || []).filter(c=>c.group===g[0]);
                let state=checks.some(c=>c.state==='error')?'error':checks.some(c=>c.state==='pending')?'warn':checks.length?'ok':'warn';
                if(active && !(d.completed_groups || []).includes(g[0]))state=!preparing && d.stage===g[0]?'working':'waiting';
                const label=state==='working'?'Проверяем':state==='waiting'?'Ожидает':state==='error'?'Ошибка':state==='warn'?'Нужна проверка':'Готово';
                return E('div',{'class':'fx-card fx-diag-card fx-border-'+state},[E('h4',{'class':'fx-'+state},[E('span',{},g[1]),E('span',{'class':'fx-stage-label'},checks.length || active?label:'')]),
                    checks.length?null:E('p',{'class':'fx-muted'},active?'Ожидаем результаты…':'Не запущено'),
                    ...checks.map((c,i)=>{
                        const key=g[0]+':'+i,open=expanded[key] ?? ['error','pending'].includes(c.state);
                        return E('details',{'class':'fx-check',open:open?true:null,toggle:ev=>expanded[key]=ev.currentTarget.open},[
                            E('summary',{},E('strong',{'class':'fx-'+(c.state==='ok'?'ok':c.state==='error'?'error':c.state==='info'?'muted':'warn')},
                                [E('span',{},c.state==='ok'?'✓ ':c.state==='error'?'✕ ':'• '),...(c.group==='outbounds' && /^[\u{1F1E6}-\u{1F1FF}]{2}/u.test(c.title)?[lab.flag(c.title).flag,' ',lab.flag(c.title).name]:[c.title])])),
                            E('div',{'class':'fx-muted fx-check-detail'},c.detail)
                        ]);
                    })].filter(child=>child!=null));
            });
            const updateErrors=Object.entries(s.updates || {}).filter(([kind,value])=>['subscription','routing'].includes(kind) && value?.state==='error');
            body.replaceChildren(
                updateErrors.length?E('div',{'class':'alert-message warning',role:'alert'},updateErrors.map(([kind,value])=>E('p',{},(kind==='subscription'?'Подписка':'Маршрутизация')+': последнее обновление не применено. '+(value.error || 'Откройте мониторинг обновлений.')+' Ниже — состояние работающей конфигурации.'))):E('span'),
                E('div',{'class':'fx-diag-toolbar'},[
                    lab.button('Запустить диагностику','diagnose','',busy),
                    lab.button('Перезапустить прокси','restart','',busy),
                    lab.button('Остановить прокси','stop','',busy),
                    E('button',{type:'button','class':'cbi-button',click:()=>lab.logs().then(r=>ui.showModal('Логи xtlsproVPN',[
                        E('pre',{'style':'max-height:60vh;overflow:auto;white-space:pre-wrap'},r.text || 'Логи пусты'),
                        E('button',{'class':'cbi-button',click:ui.hideModal},'Закрыть')]))},'Логи'),
                    E('span',{'class':'fx-muted'},'Проверка: '+lab.when(d.checked))
                ]),progress,lab.jobNote(s),
                E('div',{'class':'fx-diagnostics'},[
                    E('div',{'class':'fx-diag-column'},blocks.slice(0,3)),
                    E('div',{'class':'fx-diag-column'},blocks.slice(3))
                ]),
                E('p',{'class':'fx-muted'},(s.model || 'OpenWrt')+' · xtlsproVPN · RAM '+lab.bytes(s.core.rss)+' · нагрузка '+s.load+' · Нажмите строку проверки, чтобы раскрыть подробности.'));
        };
        draw(initial);poll.add(()=>Promise.all([lab.status(),lab.diagnostics()]).then(draw),3);
        return E('div',{},[lab.style(),E('h2',{},'xtlsproVPN'),body]);
    },handleSaveApply:null,handleSave:null,handleReset:null
});
