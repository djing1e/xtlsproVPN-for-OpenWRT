'use strict';
'require baseclass';
'require rpc';
'require poll';
'require ui';
const get=rpc.declare({object:'xray_lab_dns',method:'get',expect:{}});
const launch=rpc.declare({object:'xray_lab_dns',method:'launch',params:['action','settings'],expect:{}});
return baseclass.extend({
    render:function(initial){
        const inputs={},state=E('p',{role:'status','aria-live':'polite'}),buttons=[];
        let busy=false,submitting=false,lastJob=initial.job?.id;
        const box=E('div',{'class':'cbi-map'},[
            E('h2',{},'Маршрутизация'),
            E('p',{},'Личные правила применяются раньше списков маршрутизации. При совпадении приоритет: блокировка → тоннель → напрямую. Доступ к локальной сети и серверам подключения сохраняется. Отключение QUIC имеет приоритет над личными правилами.'),
            ...[['proxy','Через тоннель'],['direct','Напрямую'],['block','Блокировать']].map(([key,title])=>{
                const rows=['domains','ips'].map(type=>{
                    const id=key+'_'+type;
                    const node=inputs[id]=E('textarea',{id:'rules-'+id,rows:5,'class':'cbi-input-textarea',style:'width:100%;box-sizing:border-box',spellcheck:'false'});
                    return E('div',{'class':'cbi-value'},[
                        E('label',{'class':'cbi-value-title','for':'rules-'+id},type==='domains'?'Домены':'IP-адреса и подсети'),
                        E('div',{'class':'cbi-value-field'},[node,E('small',{},type==='domains'?'По одному на строке. example.com включает поддомены; full:example.com — только точное имя. Допустимы keyword: и regexp:. Кириллицу укажите в Punycode.':'IPv4, IPv6 или CIDR, например 203.0.113.5 или 203.0.113.0/24. Перехват IPv6 этими правилами не включается.')])
                    ]);
                });
                return E('section',{'class':'cbi-section'},[E('h3',{},title),...rows]);
            })
        ]);
        function fill(rules){for(const [key,node] of Object.entries(inputs))node.value=(rules?.[key] || []).join('\n');}
        function refresh(){for(const n of [...Object.values(inputs),...buttons])n.disabled=busy || submitting;}
        function draw(s){
            const j=s.job || {};busy=['pending','running'].includes(j.state);
            if(j.action?.startsWith('route_'))state.textContent=j.message || '';
            if(j.id && j.id!==lastJob && j.action==='route_apply' && j.state==='done'){fill(s.rules);lastJob=j.id;}
            refresh();
        }
        async function run(action){
            try{
                const settings=Object.fromEntries(Object.entries(inputs).map(([k,n])=>[k,n.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)]));
                submitting=true;refresh();const result=await launch(action,JSON.stringify(settings));
                if(result.error)throw Error(result.error);state.textContent='Проверяем правила…';draw(await get());
            }catch(e){ui.addNotification(null,E('p',{},e.message),'error');}finally{submitting=false;refresh();}
        }
        buttons.push(E('button',{type:'button','class':'cbi-button cbi-button-action',click:()=>run('route_test')},'Проверить без применения'));
        buttons.push(E('button',{type:'button','class':'cbi-button cbi-button-apply',click:()=>run('route_apply')},'Сохранить и применить правила'));
        box.append(E('p',{},'Применение перезапускает прокси после проверки конфигурации. При ошибке DNS или HTTPS предыдущая конфигурация возвращается.'),E('div',{'class':'cbi-page-actions'},buttons),state);
        fill(initial.rules);draw(initial);poll.add(()=>get().then(draw),3);return box;
    }
});
