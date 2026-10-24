
'use strict';
'require view.xray.core_update_transfer2 as coreUpdate';
'require view.xray.dns_panel as dnsSettings';
'require view.xray.schedule as schedule';
'require view.xray.netbird as netbird';
'require view.xray.memory as memoryPanel';
'require view.xray.subscription as subscriptionPanel';
'require view';
'require form';
'require uci';
'require tools.widgets as widgets';
'require view.xray.lab_052 as lab';
'require view.xray.routing_panel as routingPanel';

return view.extend({
    load:function(){return Promise.all([uci.load('xray_core'),dnsSettings.load()]);},
    render:function(initial){
        const map=new form.Map('xray_core','Настройки xtlsproVPN');
        const section=map.section(form.NamedSection,'general','general');
        let o=section.option(form.Value,'fx_probe_url','URL проверки задержки','HTTPS-страница, отвечающая HTTP 204.');
        o.rmempty=false;o.validate=(sid,v)=>/^https:\/\/[^\s]+$/i.test(v)?true:'Требуется HTTPS-адрес.';
        o=section.option(form.Value,'fx_probe_interval','Интервал проверки локаций, секунд');o.datatype='range(30,3600)';o.rmempty=false;
        o=section.option(form.Flag,'fx_watchdog_enabled','Мониторинг интерфейса / watchdog');o.rmempty=false;
        o=section.option(widgets.NetworkSelect,'fx_watch_interface','Наблюдаемый интерфейс',
            'На текущем тестовом роутере интернет проходит через LAN. При обычной схеме выберите WAN / PPPoE.');
        o.nocreate=true;o.multiple=false;o.rmempty=false;
        o=section.option(form.Value,'fx_watch_delay','Задержка после подъёма интерфейса, мс');o.datatype='range(1000,60000)';o.rmempty=false;
        o=section.option(form.Flag,'fx_access_log','Журнал соединений','Выключен по умолчанию. При включении хранится в RAM и сокращается монитором; используйте для диагностики.');o.rmempty=false;
        return Promise.all([map.render(),subscriptionPanel.render(),schedule.render(),coreUpdate.render(),dnsSettings.render(initial[1]),routingPanel.render(initial[1]),netbird.render(),memoryPanel.render().catch(error=>E('div',{'class':'alert-message warning'},'Не удалось загрузить настройки памяти: '+(error.message || String(error))))]).then(parts=>{
            const content=E('div'), tabs=E('div',{'class':'xt-tabs',role:'tablist','aria-label':'Разделы настроек'});
            const panels=[], controls=[];
            const labels=['Подписка','DNS и сеть','Маршрутизация','Автообновление','Ядро','Память','Административный доступ','Дополнительно'];
            const items=[parts[1],parts[4],parts[5],parts[2],parts[3],parts[7],parts[6],parts[0]];
            function select(index){
                panels.forEach((p,i)=>{p.style.display=i===index?'':'none';});
                controls.forEach((b,i)=>{b.setAttribute('aria-selected',String(i===index));b.tabIndex=i===index?0:-1;});
            }
            labels.forEach((label,i)=>{
                const button=E('button',{type:'button',id:'xt-tab-'+i,role:'tab','aria-controls':'xt-panel-'+i,
                    'class':'cbi-button',click:()=>select(i),keydown:ev=>{
                        if(!['ArrowLeft','ArrowRight','Home','End'].includes(ev.key))return;
                        ev.preventDefault();const next=ev.key==='Home'?0:ev.key==='End'?labels.length-1:(i+(ev.key==='ArrowRight'?1:labels.length-1))%labels.length;
                        select(next);controls[next].focus();
                    }},label);
                controls.push(button);tabs.append(button);
                const panel=E('div',{id:'xt-panel-'+i,role:'tabpanel','aria-labelledby':'xt-tab-'+i},[items[i]]);
                panels.push(panel);content.append(panel);
            });
            select(location.hash==='#memory'?5:location.hash==='#dns'?1:0);
            return E('div',{'class':'xt-settings'},[lab.style(),
                E('style',{},'.xt-settings{max-width:1100px}.xt-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.xt-tabs [aria-selected="true"]{border-color:#00b991;color:#00b991}.xt-settings .cbi-map{margin-top:0}'),
                E('h2',{},'xtlsproVPN'),tabs,content,
                E('p',{'class':'fx-muted'},'Дополнительные параметры сохраняются кнопкой внизу страницы. Подписка имеет собственную кнопку сохранения. DNS, маршрутизация, расписание, память, ядро и NetBird имеют собственные кнопки.')]);
        });
    }
});
