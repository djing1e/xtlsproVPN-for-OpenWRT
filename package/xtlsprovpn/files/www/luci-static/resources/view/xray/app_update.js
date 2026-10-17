'use strict';
'require view';
'require rpc';
'require poll';
'require ui';

const status = rpc.declare({object:'xray_lab_package',method:'status'});
const launch = rpc.declare({object:'xray_lab_package',method:'launch',params:['action','version','sha256']});

return view.extend({
    handleSave:null,handleSaveApply:null,handleReset:null,
    load:function() {return status();},
    render:function(initial) {
        let current=initial, submitting=false;
        const installed=E('p'), available=E('p'), message=E('p',{role:'status','aria-live':'polite'});
        const release=E('a',{target:'_blank',rel:'noopener noreferrer'},'Описание релиза');
        const check=E('button',{type:'button','class':'cbi-button cbi-button-action',click:()=>action('check')},'Проверить обновление');
        const install=E('button',{type:'button','class':'cbi-button cbi-button-apply',click:()=>confirmInstall()},'Установить обновление');
        function refresh(data) {
            if (data.error) throw new Error(data.error);
            current=data;
            const job=data.job || {}, candidate=data.catalog;
            const busy=submitting || ['pending','running'].includes(job.state);
            installed.textContent='Установлено: '+(data.installed || 'версия не определена');
            available.textContent=candidate ? 'Стабильный релиз: '+candidate.version+
                (data.available?' — доступно обновление':' — обновление не требуется') : 'Проверка стабильного релиза ещё не выполнялась.';
            // Only the backend constructs a link to the fixed official repository.
            release.style.display=candidate?'':'none';
            if (candidate) release.setAttribute('href',candidate.release_url);
            message.textContent=job.message || '';
            message.style.color=['failed','interrupted'].includes(job.state)?'#c0392b':'';
            check.disabled=busy;
            install.disabled=busy || !data.available || !candidate || !data.installed;
        }
        function action(name,version,sha256) {
            if (submitting) return Promise.resolve();
            submitting=true;refresh(current);
            message.textContent='Запускаем операцию…';
            return launch(name,version || '',sha256 || '').then(result=>{
                if (!result.ok) throw new Error(result.error || 'Операция не запущена');
                return status();
            }).then(data=>{submitting=false;refresh(data);}).catch(error=>{
                submitting=false;refresh(current);
                message.textContent=error.message || String(error);
            });
        }
        function confirmInstall() {
            if (install.disabled) return;
            const candidate=current.catalog;
            ui.showModal('Обновить xtlsproVPN до '+candidate.version+'?',[
                E('p',{},'Настройки, подписка, ядро Xray и регистрация NetBird сохраняются. Во время установки возможен краткий перерыв связи. Не отключайте питание.'),
                E('p',{},'Перед установкой сохраняется резервная копия настроек. Автоматический откат APK при ошибке пока не выполняется.'),
                E('div',{'class':'right'},[
                    E('button',{type:'button','class':'cbi-button',click:ui.hideModal},'Отмена'),
                    E('button',{type:'button','class':'cbi-button cbi-button-apply',click:()=>{
                        ui.hideModal();return action('install',candidate.version,candidate.sha256);
                    }},'Обновить')])]);
        }
        refresh(initial);
        poll.add(()=>status().then(refresh).catch(()=>{
            message.textContent='Ожидаем связь с LuCI. Установщик продолжает работу; после восстановления соединения статус обновится.';
            install.disabled=true;
        }),5);
        return E('div',{'class':'cbi-map'},[
            E('h2',{},'Обновление приложения xtlsproVPN'),
            E('p',{},'Здесь обновляется APK приложения. Ядро Xray и NetBird управляются отдельно. Проверяются только стабильные релизы официального репозитория.'),
            installed,available,release,message,E('div',{},[check,' ',install]),
            E('p',{'class':'description'},'Обновление запускается только по кнопке. Проверяются платформа, свободное место, размер и SHA-256 APK. После завершения обновите страницу браузера.')]);
    }
});
