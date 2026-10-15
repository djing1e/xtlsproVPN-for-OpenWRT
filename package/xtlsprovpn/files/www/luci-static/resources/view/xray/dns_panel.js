'use strict';
'require baseclass';
'require rpc';
'require poll';
'require ui';

const get = rpc.declare({object:'xray_lab_dns',method:'get',expect:{}});
const launch = rpc.declare({object:'xray_lab_dns',method:'launch',params:['action','settings'],expect:{}});

return baseclass.extend({
    load: function() { return get(); },
    render: function(initial) {
        if (!initial.options) throw new Error(initial.error || 'Не удалось загрузить настройки DNS');
        const fields={}, rows={}, providers=initial.providers || {}, state=E('p',{'role':'status','aria-live':'polite'});
        const box=E('div',{'class':'cbi-map'}), buttons=[];
        let busy=false, submitting=false, loadedJob=initial.job?.id;
        const sourceWidget=new ui.Dropdown([],Object.fromEntries(initial.devices.map(n=>[n,n])),{
            id:'dns-sources',multiple:true,optional:true,display_items:3,select_placeholder:'LAN текущего профиля'
        });
        const bootstrapWidget=new ui.Dropdown([],{
            '1.1.1.1':'1.1.1.1 (Cloudflare)','1.0.0.1':'1.0.0.1 (Cloudflare)',
            '8.8.8.8':'8.8.8.8 (Google)','8.8.4.4':'8.8.4.4 (Google)',
            '9.9.9.9':'9.9.9.9 (Quad9)','149.112.112.112':'149.112.112.112 (Quad9)',
            '77.88.8.8':'77.88.8.8 (Яндекс)','77.88.8.1':'77.88.8.1 (Яндекс)',
            '94.140.14.14':'94.140.14.14 (AdGuard)'
        },{id:'dns-bootstrap',multiple:true,optional:false,create:true,datatype:'list(ipaddr)',
            display_items:3,select_placeholder:'Выберите сервер',custom_placeholder:'Свой IP-адрес'});
        function row(key,title,node,help) {
            fields[key]=node;
            return rows[key]=E('div',{'class':'cbi-value'},[
                E('label',{'class':'cbi-value-title','for':'dns-'+key},title),
                E('div',{'class':'cbi-value-field'},[node,help?E('div',{'class':'cbi-value-description'},help):''])
            ]);
        }
        function flag(key,title,help) { return row(key,title,E('input',{id:'dns-'+key,type:'checkbox',change:refresh}),help); }
        function select(key,title,items,help) { return row(key,title,E('select',{id:'dns-'+key,'class':'cbi-input-select',change:refresh},items.map(x=>E('option',{value:x[0]},x[1]))),help); }
        function text(key,title,help,multi) { return row(key,title,E(multi?'textarea':'input',{
            id:'dns-'+key,type:multi?null:'text',rows:multi?3:null,'class':multi?'cbi-input-textarea':'cbi-input-text',input:refresh
        }),help); }
        const dns=E('div',{'class':'cbi-section'},[
            E('h3',{},'DNS'),
            flag('enabled','Использовать свои настройки DNS','Когда выключено, DNS определяется текущим профилем маршрутизации.'),
            select('protocol','Тип протокола DNS',[['doh','DNS over HTTPS (DoH)'],['dot','DNS over TLS (DoT)'],['udp','DNS по UDP'],['tcp','DNS по TCP']]),
            select('provider','DNS-серверы',[...Object.entries(providers).map(([k,v])=>[k,v.name]),['custom','Свой сервер']]),
            text('servers','Адреса DNS-серверов','До четырёх адресов, по одному на строке.',true),
            row('preset','Адреса провайдера',E('code',{})),
            row('bootstrap','Bootstrap DNS-серверы',bootstrapWidget.render(),'До четырёх IP-адресов. Разрешают имена DNS-серверов, узлов и проверки задержки напрямую.'),
            select('strategy','Стратегия DNS',[['ipv4','IPv4'],['ipv6','IPv6'],['auto','Автоматически (IPv4 и IPv6)']],
                'Стратегия выбирает ответы DNS. Проксирование клиентского IPv6 этим не включается.'),
            flag('via_proxy','DNS через прокси','Основные запросы идут через выбранную локацию или балансировщик; bootstrap остаётся прямым.'),
            flag('ttl_enabled','Перезапись TTL для DNS','Меняет TTL в ответах DNS. При включении работает небольшой локальный обработчик; кэш dnsmasq отключается.'),
            text('ttl','TTL, секунд','От 0 до 86400. TTL = 0 запрещает кэширование ответа.')
        ]);
        const network=E('div',{'class':'cbi-section'},[
            E('h3',{},'Сеть'),
            row('sources','Сетевые интерфейсы источника',sourceWidget.render(),
                'Входящие устройства клиентов, например br-lan. Без выбора используется LAN текущего профиля.'),
            flag('output_enabled','Выбрать выходной сетевой интерфейс','По умолчанию выход определяется таблицей маршрутизации автоматически.'),
            select('output_device','Выходной сетевой интерфейс', [['','Выберите устройство'],...initial.devices.map(n=>[n,n])]),
            flag('disable_quic','Отключить QUIC','Блокирует клиентский UDP/443 для совместимости и устранения проблем с видео. Приложения с поддержкой TCP смогут переключиться на него.')
        ]);
        function refresh() {
            const on=fields.enabled.checked;
            for (const k of ['protocol','provider','bootstrap','strategy','via_proxy','ttl_enabled']) fields[k].disabled=!on || busy || submitting;
            rows.servers.style.display=fields.provider.value==='custom'?'':'none';
            rows.preset.style.display=fields.provider.value==='custom'?'none':'';
            rows.output_device.style.display=fields.output_enabled.checked?'':'none';
            rows.ttl.style.display=fields.ttl_enabled.checked?'':'none';
            fields.servers.disabled=!on || busy || submitting;
            fields.ttl.disabled=!on || !fields.ttl_enabled.checked || busy || submitting;
            fields.output_device.disabled=!fields.output_enabled.checked || busy || submitting;
            fields.enabled.disabled=fields.output_enabled.disabled=fields.disable_quic.disabled=busy || submitting;
            for(const [node,disabled] of [[fields.sources,busy || submitting],[fields.bootstrap,!on || busy || submitting]]) {
                if(disabled) node.setAttribute('disabled',''); else node.removeAttribute('disabled');
            }
            const preset=providers[fields.provider.value];
            fields.preset.textContent=preset?(preset[fields.protocol.value==='tcp'?'udp':fields.protocol.value] || []).join(', '):'';
            fields.servers.placeholder={doh:'https://dns.example/dns-query',dot:'dns.example:853',udp:'1.1.1.1',tcp:'1.1.1.1:53'}[fields.protocol.value];
            buttons.forEach(b=>b.disabled=busy || submitting);
        }
        function fill(options) {
            for (const [key,node] of Object.entries(fields)) {
                if (key==='preset') continue;
                if (key==='sources') sourceWidget.setValue(options.sources || []);
                else if (key==='bootstrap') bootstrapWidget.setValue(options.bootstrap || []);
                else if (node.type==='checkbox') node.checked=options[key]==='1';
                else node.value=Array.isArray(options[key])?options[key].join('\n'):options[key] || '';
            }
            refresh();
        }
        function read() {
            const o={};
            for (const [k,node] of Object.entries(fields)) {
                if(k==='preset') continue;
                o[k]=k==='sources'?sourceWidget.getValue():k==='bootstrap'?bootstrapWidget.getValue():node.type==='checkbox'?(node.checked?'1':'0'):
                    ['servers','bootstrap'].includes(k)?node.value.split(/\s+/).filter(Boolean):node.value;
            }
            if(!/^\d{1,5}$/.test(o.ttl) || +o.ttl>86400) throw new Error('TTL должен быть от 0 до 86400 секунд.');
            return o;
        }
        function draw(s) {
            const j=s.job || {};
            busy=['pending','running'].includes(j.state);
            state.textContent=j.message || 'Настройки ещё не проверялись. Проверка не меняет рабочий тоннель.';
            state.className=j.state==='failed' || j.state==='interrupted'?'alert-message error':j.state==='done'?'alert-message success':'alert-message';
            if(j.id && j.id!==loadedJob && j.state==='done' && j.phase==='applied') {fill(s.options);loadedJob=j.id;}
            refresh();
        }
        async function run(action) {
            try {
                const settings=action==='restore'?'{}':JSON.stringify(read());submitting=true;refresh();
                state.textContent='Отправляем настройки…';
                const result=await launch(action,settings);
                if(result.error) throw new Error(result.error);
                draw(await get());
            } catch(e) {ui.addNotification(null,E('p',{},e.message),'error');}
            finally {submitting=false;refresh();}
        }
        buttons.push(E('button',{'class':'cbi-button cbi-button-action',click:()=>run('test')},'Проверить без применения'));
        buttons.push(E('button',{'class':'cbi-button cbi-button-apply',click:()=>run('apply')},'Сохранить и применить'));
        buttons.push(E('button',{'class':'cbi-button',type:'button',click:()=>ui.showModal('Восстановить DNS',[
            E('p',{},'Будут установлены прямые DNS 1.1.1.1 и 8.8.8.8 по UDP, IPv4, без перезаписи TTL. Сетевые интерфейсы и QUIC сохранятся. Прокси перезапустится после проверки. При неудаче предыдущие настройки вернутся.'),
            E('div',{'class':'right'},[
                E('button',{'class':'cbi-button',click:ui.hideModal},'Отмена'),
                E('button',{'class':'cbi-button cbi-button-apply',click:()=>{ui.hideModal();run('restore');}},'Восстановить DNS')])
        ])},'Восстановить DNS'));
        box.append(E('h2',{},'DNS и сеть'),dns,network,E('div',{'class':'cbi-section'},[
            E('p',{},'Применение повторяет проверку и перезапускает xtlsproVPN. При неудачной проверке соединения возвращаются предыдущие настройки.'),
            E('div',{'class':'cbi-page-actions'},buttons),state
        ]));
        fill(initial.options);draw(initial);
        poll.add(()=>get().then(draw),3);
        return box;
    },
    handleSaveApply:null,handleSave:null,handleReset:null
});
