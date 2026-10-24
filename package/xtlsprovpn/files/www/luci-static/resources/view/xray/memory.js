'use strict';
'require baseclass';
'require rpc';
'require poll';
const get=rpc.declare({object:'xray_lab_zram',method:'status'});
const apply=rpc.declare({object:'xray_lab_zram',method:'apply',params:['enabled','size_mb','algorithm']});
function mib(kb){return (Number(kb || 0)/1024).toFixed(1)+' МиБ';}
return baseclass.extend({
    render:function(){
        return get().then(data=>{
            if(data.error)throw new Error(data.error);
            let current=data,submitting=false,error=null,algorithmList=JSON.stringify(data.algorithms);
            const enabled=E('input',{type:'checkbox','aria-label':'Включить ZRAM',checked:data.enabled?true:null});
            const sizes=[64,128,256,512,1024].filter(n=>n<=data.total_kb/512);
            const size=E('select',{'class':'cbi-input-select','aria-label':'Размер ZRAM'},sizes.map(n=>E('option',{value:String(n),selected:n===data.size_mb?true:null},n+' МиБ')));
            const algo=E('select',{'class':'cbi-input-select','aria-label':'Алгоритм ZRAM'},data.algorithms.map(a=>E('option',{value:a,selected:a===data.algorithm?true:null},a)));
            const summary=E('p',{role:'status','aria-live':'polite'});
            const message=E('p',{role:'status','aria-live':'polite'});
            const button=E('button',{type:'button','class':'cbi-button cbi-button-apply',click:()=>{
                if(submitting || ['pending','running'].includes(current.job?.state))return;
                error=null;submitting=true;update(current);message.textContent='Применяем настройки памяти…';
                return apply(enabled.checked?'1':'0',size.value,algo.value).then(r=>{
                    if(!r.ok)throw new Error(r.error || 'Ошибка применения ZRAM');
                    current={...current,job:{state:'pending',message:'Применяем настройки памяти…'}};
                }).catch(e=>{error=e.message || String(e);}).finally(()=>{submitting=false;update(current);});
            }},data.installed?'Применить':'Установить и включить ZRAM');
            function update(s){
                current=s;
                if(JSON.stringify(s.algorithms)!==algorithmList){
                    const chosen=s.algorithms.includes(algo.value)?algo.value:s.algorithm;
                    algo.replaceChildren(...s.algorithms.map(a=>E('option',{value:a,selected:a===chosen?true:null},a)));
                    algorithmList=JSON.stringify(s.algorithms);
                }
                const busy=submitting || ['pending','running'].includes(s.job?.state);
                enabled.disabled=busy || !s.managed;size.disabled=busy || !s.managed;algo.disabled=busy || !s.managed;
                button.disabled=busy || !s.managed;
                button.textContent=s.installed?'Применить':'Установить и включить ZRAM';
                let active=s.swaps[0];
                summary.textContent='RAM: '+mib(s.total_kb)+'; доступно '+mib(s.available_kb)+'. '+
                    (active?'ZRAM: '+mib(active.size_kb)+', занято '+mib(active.used_kb)+', '+(s.active_algorithm || '—')+', приоритет '+active.priority+'.':'ZRAM не активен.')+
                    ' Автозапуск: '+(s.enabled?'включён.':'выключен.');
                if(error || s.job?.message)message.textContent=error || s.job.message;
                message.style.color=error || s.job?.state==='failed'?'#c0392b':'';
                if(!s.managed)message.textContent='Обнаружена нестандартная конфигурация ZRAM. Автоматическое изменение недоступно.';
            }
            // First install is explicit. Reading this page never installs or enables swap.
            enabled.checked=data.installed?data.enabled:true;
            update(data);
            poll.add(()=>get().then(s=>{if(s.error)throw new Error(s.error);update(s);}).catch(e=>{error=e.message || String(e);}),5);
            return E('div',{'class':'cbi-section'},[
                E('h3',{},'Память и ZRAM'),
                E('p',{},'ZRAM хранит сжатые страницы памяти в RAM. Размер — ёмкость подкачки; память выделяется по мере использования. Для роутера с 256 МиБ RAM проверен размер 128 МиБ и lzo.'),
                summary,
                E('label',{style:'display:block;margin:12px 0'},[enabled,' Включить ZRAM и автозапуск']),
                E('label',{style:'display:block;margin:12px 0'},['Размер: ',size]),
                E('label',{style:'display:block;margin:12px 0'},['Сжатие: ',algo]),
                E('p',{},'При первом включении установится пакет zram-swap из репозитория OpenWrt. Изменение активного ZRAM требует его перезапуска; при нехватке свободной RAM операция будет отклонена.'),
                button,message]);
        });
    }
});
