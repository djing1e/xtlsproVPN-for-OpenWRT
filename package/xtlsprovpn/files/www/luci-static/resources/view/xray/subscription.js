'use strict';
'require baseclass';
'require rpc';
const status=rpc.declare({object:'xray_lab_subscription',method:'status'});
const save=rpc.declare({object:'xray_lab_subscription',method:'save',params:['subscription_url','user_agent','hwid_enabled','hwid']});
return baseclass.extend({
    render:function(){return status().then(function(data){
        if(data.error)throw new Error(data.error);
        const url=E('input',{type:'password',autocomplete:'new-password','aria-label':'Новая ссылка подписки',placeholder:data.configured?'Подписка настроена. Введите новую ссылку для замены.':'https://…'});
        const ua=E('input',{type:'text',value:data.user_agent || '',placeholder:'Xray/версия установленного ядра','aria-label':'User-Agent'});
        const enabled=E('input',{type:'checkbox','aria-label':'Передавать HWID'});enabled.checked=data.hwid_enabled==='1';
        const hwid=E('input',{type:'password',value:data.hwid || '',autocomplete:'new-password','aria-label':'Свой HWID'});
        const message=E('p',{role:'status','aria-live':'polite'});
        let busy=false;
        const button=E('button',{type:'button','class':'cbi-button cbi-button-apply',click:function(){
            if(busy)return;
            if(url.value && !/^https:\/\/[^\s]+$/i.test(url.value.trim())){message.textContent='Требуется HTTPS-ссылка подписки';return;}
            busy=true;button.disabled=true;const secret=url.value.trim();url.value='';
            save(secret,ua.value.trim(),enabled.checked?'1':'0',hwid.value.trim()).then(function(r){
                if(!r.ok)throw new Error(r.error || 'Не удалось сохранить');
                url.placeholder='Подписка настроена. Введите новую ссылку для замены.';
                message.textContent='Сохранено. Обновите подписку на дашборде для применения.';
            }).catch(function(e){message.textContent=e.message || String(e);}).finally(function(){busy=false;button.disabled=false;});
        }},'Сохранить подписку');
        function row(label,input,description){return E('div',{'class':'cbi-value'},[E('label',{'class':'cbi-value-title'},label),E('div',{'class':'cbi-value-field'},[input,E('div',{'class':'cbi-value-description'},description || '')])]);}
        return E('div',{'class':'cbi-map'},[E('h2',{},'Подписка'),
            row('Заменить URL подписки',url,'Сохранённая ссылка не передаётся в браузер. Пустое поле сохраняет текущую подписку.'),
            row('User-Agent',ua),row('Передавать HWID',enabled,'Постоянный идентификатор роутера для учёта устройств на сервере подписок.'),
            row('Свой HWID',hwid,'Оставьте пустым для постоянного идентификатора роутера.'),button,message]);
    }).catch(function(e){return E('p',{'class':'alert-message error'},'Не удалось загрузить настройки подписки: '+(e.message || String(e)));});}
});
