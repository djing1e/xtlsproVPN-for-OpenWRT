'use strict';
'require baseclass';
'require rpc';
'require poll';

const get=rpc.declare({object:'xray_lab_core',method:'get'});
const launch=rpc.declare({
    object:'xray_lab_core',method:'launch',params:['action','version']
});
const savePreferences=rpc.declare({
    object:'xray_lab_core',method:'settings',
    params:['include_prerelease','pinned_version']
});

return baseclass.extend({
    render:function(){
        return get().then(function(initial){
            const body=E('div',{'class':'cbi-map'});
            let data=initial, selected='', pinDraft=initial.pinned_version || '';
            let pending=false, error='';

            function busy(){
                return pending || ['pending','running'].includes(data.job?.state);
            }
            function refresh(){
                return get().then(function(value){data=value;draw();});
            }
            function act(action){
                pending=true;error='';draw();
                return launch(action,selected).then(function(result){
                    if(!result.ok) throw new Error(result.error || 'Ошибка запуска');
                }).catch(function(e){
                    error=e.message || String(e);
                }).finally(function(){
                    pending=false;
                    refresh().catch(function(e){error=e.message;draw();});
                });
            }
            function preferences(show,pin){
                pending=true;error='';draw();
                return savePreferences(show?'1':'0',pin).then(function(result){
                    if(!result.ok) throw new Error(result.error || 'Ошибка сохранения');
                    return get();
                }).then(function(value){
                    data=value;pending=false;
                    selected='';
                    return act('list');
                }).catch(function(e){
                    pending=false;error=e.message || String(e);draw();
                });
            }
            function button(label,action,disabled){
                return E('button',{
                    type:'button','class':'cbi-button',
                    disabled:disabled?true:null,
                    click:function(){return act(action);}
                },label);
            }
            function older(a,b){
                const x=a.split('.').map(Number),y=b.split('.').map(Number);
                for(let i=0;i<3;i++){
                    if(x[i]!==y[i]) return x[i]<y[i];
                }
                return false;
            }
            function draw(){
                const locked=busy(),u=data.update || {},j=data.job || {};
                const releases=(data.catalog?.releases || []).filter(function(r){
                    return data.include_prerelease || r.prerelease!==true;
                });
                if(selected && !releases.some(r=>r.version===selected)) selected='';
                if(!selected && data.pinned_version &&
                    releases.some(r=>r.version===data.pinned_version))
                    selected=data.pinned_version;

                const ready=selected && u.action==='test' &&
                    u.phase==='compatible' && u.available===selected;
                const failed=['failed','interrupted'].includes(j.state);
                let message=u.message || 'Обновите список и выберите версию.';
                if(failed && (!u.updated || u.updated<(j.started || 0)))
                    message='Операция не завершена. Возможно, выполняется другая задача xtlsproVPN.';
                if(j.state==='interrupted')
                    message='Операция прервана. Проверьте диагностику.';
                if(error) message=error;

                const phases={
                    release:'Получение релизов',
                    preflight:'Проверка тоннеля',
                    download:'Загрузка',
                    checksum:'Проверка SHA-256',
                    extract:'Распаковка',
                    validating:'Проверка конфигурации',
                    staging:'Подготовка замены',
                    restarting:'Перезапуск xtlsproVPN',
                    verifying:'Проверка соединения'
                };
                const selector=E('select',{
                    'class':'cbi-input-select',
                    disabled:locked?true:null,
                    'aria-label':'Версия xtlsproVPN',
                    change:function(ev){selected=ev.target.value;draw();}
                },[
                    E('option',{value:'',selected:!selected?true:null},'Выберите версию'),
                    ...releases.map(function(r){
                        return E('option',{
                            value:r.version,
                            selected:r.version===selected?true:null
                        },r.version+(r.prerelease?' · prerelease':' · stable')+
                            (r.version===data.installed?' — установлена':'')+
                            (r.version===data.pinned_version?' ★':''));
                    })
                ]);

                body.replaceChildren(
                    E('h2',{},'Ядро xtlsproVPN'),
                    E('p',{},'Установлено: '+(data.installed || 'не определено')+
                        (data.rollback_available?' · Резервная версия доступна':'')),
                    E('label',{
                        style:'display:flex;align-items:center;gap:8px;margin:12px 0'
                    },[
                        E('input',{
                            type:'checkbox',
                            checked:data.include_prerelease?true:null,
                            disabled:locked?true:null,
                            change:function(ev){
                                return preferences(ev.target.checked,data.pinned_version || '');
                            }
                        }),
                        E('span',{},'Показывать prerelease')
                    ]),
                    E('div',{
                        style:'display:flex;align-items:center;gap:8px;flex-wrap:wrap'
                    },[
                        selector,
                        button('Обновить список','list',locked),
                        button('Проверить совместимость','test',locked || !selected),
                        button('Установить выбранную','install',
                            locked || !ready || selected===data.installed),
                        button('Откатить ядро','rollback',locked || !data.rollback_available),
                        button('Удалить резервную копию','purge-backup',
                            locked || !data.rollback_available)
                    ]),
                    selected && data.installed && older(selected,data.installed)?
                        E('p',{style:'color:#b77900'},
                            'Выбрана версия старше установленной. Это понижение версии.'):
                        E('span'),
                    E('div',{
                        style:'display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:14px'
                    },[
                        E('label',{},'Закреплённая версия:'),
                        E('input',{
                            type:'text',value:pinDraft,placeholder:'26.7.28',
                            'class':'cbi-input-text',style:'width:10em',
                            disabled:locked?true:null,
                            'aria-label':'Номер закреплённой версии',
                            input:function(ev){pinDraft=ev.target.value;}
                        }),
                        E('button',{
                            type:'button','class':'cbi-button',
                            disabled:locked?true:null,
                            click:function(){
                                return preferences(data.include_prerelease,pinDraft.trim());
                            }
                        },'Сохранить'),
                        E('button',{
                            type:'button','class':'cbi-button',
                            disabled:locked || !selected?true:null,
                            click:function(){
                                pinDraft=selected;
                                return preferences(data.include_prerelease,selected);
                            }
                        },'Закрепить выбранную')
                    ]),
                    E('p',{style:'opacity:.75;font-size:.9em'},
                        'Закрепление сохраняет предпочтительную версию и добавляет её в каталог. Пустое поле снимает закрепление. Автоматической установки нет.'),
                    E('p',{
                        role:'status','aria-live':'polite',
                        style:'overflow-wrap:anywhere;color:'+
                            (error || failed || ['error','recovery_failed'].includes(u.phase)?
                                '#c0392b':['compatible','done'].includes(u.phase)?
                                    '#218739':'inherit')
                    },[
                        locked?E('strong',{},(phases[u.phase] || 'Запуск операции')+'… '):E('span'),
                        E('span',{},message)
                    ]),
                    E('p',{style:'opacity:.75;font-size:.9em'},
                        'Prerelease доступны только при включённом переключателе. Перед установкой конфигурация проверяется повторно. По умолчанию резервное ядро удаляется после успешной проверки запуска.')
                );
            }
            draw();
            poll.add(refresh,3);
            return body;
        }).catch(function(e){
            return E('div',{'class':'alert-message warning'},
                'Не удалось загрузить управление ядром: '+e.message);
        });
    }
});
