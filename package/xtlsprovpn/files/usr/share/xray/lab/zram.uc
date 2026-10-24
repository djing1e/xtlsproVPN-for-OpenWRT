#!/usr/bin/ucode
"use strict";
import * as fs from 'fs';
import { cursor } from 'uci';
const root=getenv('FX_ZRAM_ROOT') || '',run=root+'/var/run/xtlspro-zram';
const service=root+'/etc/init.d/zram';
function quote(s){return "'"+replace(''+s,/'/g,"'\\''")+"'";}
function command(args,seconds){
    let p=fs.popen(join(' ',map(['timeout','-k','5',''+seconds,...args],quote))+' 2>/dev/null','r');
    if(!p)return {ok:false,text:''};
    let text=p.read('all') || '';return {ok:p.close()==0,text};
}
function checked(args,seconds,message){if(!command(args,seconds).ok)die(message);}
function load(path){try{return json(fs.readfile(path) || '');}catch(e){return null;}}
function save(value){
    let f=fs.open(run+'/job.json.new','w',0600);
    if(!f)die('Не удалось сохранить операцию ZRAM');
    let ok=f.write(sprintf('%J',value));f.close();
    if(!ok || !fs.rename(run+'/job.json.new',run+'/job.json'))die('Не удалось сохранить операцию ZRAM');
}
function configuration(){
    let c=cursor();let all=c.get_all('system') || {};
    for(let name,s in all)if(s['.type']=='system')return {c,name,s};
    die('Не найден раздел system');
}
function status(){
    let cfg=configuration(),mem=fs.readfile(root+'/proc/meminfo') || '';
    function kb(key){return int(match(mem,regexp(key+':[[:space:]]+([0-9]+)'))?.[1] || 0);}
    let swaps=[];
    for(let line in split(fs.readfile(root+'/proc/swaps') || '','\n')){
        let v=split(trim(line),/[[:space:]]+/);
        if(match(v[0] || '',/^\/dev\/zram[0-9]+$/))push(swaps,{device:v[0],size_kb:int(v[2]),used_kb:int(v[3]),priority:int(v[4])});
    }
    let algorithms=split(trim(fs.readfile(root+'/sys/block/zram0/comp_algorithm') || 'lzo'),/[[:space:]]+/);
    let selected=null;
    algorithms=map(algorithms,a=>{if(index(a,'[')==0)selected=replace(replace(a,'[',''),']','');return replace(replace(a,'[',''),']','');});
    algorithms=filter(algorithms,a=>!!match(a,/^[A-Za-z0-9_-]{1,24}$/));
    let installed=!!fs.stat(service);
    return {installed,enabled:installed && command([service,'enabled'],5).ok,
        size_mb:int(cfg.s.zram_size_mb || '128'),algorithm:cfg.s.zram_comp_algo || 'lzo',
        priority:int(cfg.s.zram_priority || '100'),algorithms,active_algorithm:selected,
        total_kb:kb('MemTotal'),available_kb:kb('MemAvailable'),swaps,
        active:length(swaps)>0,managed:length(swaps)==0 || length(swaps)==1 && swaps[0].device=='/dev/zram0'};
}
function validate(p){
    if(type(p)!='object' || index(['0','1'],p.enabled)<0 ||
       !match(''+p.size_mb,/^(64|128|256|512|1024)$/) ||
       !match(p.algorithm || '',/^[A-Za-z0-9_-]{1,24}$/))die('Недопустимые настройки ZRAM');
    const s=status();
    if(int(p.size_mb)>s.total_kb/512)die('Размер ZRAM превышает допустимый для этого роутера');
    if(index(s.algorithms,p.algorithm)<0)die('Алгоритм не поддерживается ядром');
    if(!s.managed)die('Обнаружена нестандартная конфигурация ZRAM; настройки не изменены');
    return {enabled:p.enabled,size_mb:''+p.size_mb,algorithm:p.algorithm};
}
function safe_stop(s){
    if(s.active && s.available_kb<s.swaps[0].used_kb+32768)
        die('Недостаточно свободной RAM для отключения или перезапуска ZRAM. Освободите память и повторите.');
}
function perform(p){
    p=validate(p);let s=status();
    if(!s.installed && p.enabled=='0')return 'ZRAM не установлен; подкачка выключена.';
    if(!s.installed){
        checked([root+'/usr/bin/xray-zram-apk'],360,'Не удалось установить zram-swap из репозитория OpenWrt');
        s=status();if(!s.installed)die('Пакет zram-swap не установил службу zram');
        // The package may start default swap from its post-install script.
        p=validate(p);
    }
    let restart=p.enabled=='1' && (!s.active || s.swaps[0].size_kb<int(p.size_mb)*1024-8 ||
        s.swaps[0].size_kb>int(p.size_mb)*1024 || s.active_algorithm!=p.algorithm || s.swaps[0].priority!=100);
    if(p.enabled=='0' || restart)safe_stop(s);
    let cfg=configuration(),old={};
    const next={zram_size_mb:p.size_mb,zram_comp_algo:p.algorithm,zram_priority:'100'};
    for(let k,v in next){old[k]=cfg.s[k];if(!cfg.c.set('system',cfg.name,k,v))die('Не удалось подготовить настройки ZRAM');}
    if(!cfg.c.commit('system'))die('Не удалось сохранить настройки ZRAM');
    try {
        if(s.active && (p.enabled=='0' || restart)){
            checked([service,'stop'],30,'Не удалось остановить ZRAM');
            if(status().active)die('ZRAM остался активен; перезапуск отменён');
        }
        if(p.enabled=='1'){
            if(restart)checked([service,'start'],30,'Не удалось активировать ZRAM');
            let actual=status();
            if(!actual.active || actual.swaps[0].device!='/dev/zram0' ||
                actual.swaps[0].size_kb<int(p.size_mb)*1024-8 || actual.swaps[0].size_kb>int(p.size_mb)*1024 ||
                actual.active_algorithm!=p.algorithm || actual.swaps[0].priority!=100)die('Параметры активного ZRAM не совпали с выбранными');
            checked([service,'enable'],5,'Не удалось включить автозапуск ZRAM');
            return 'ZRAM '+p.size_mb+' МиБ включён; автозапуск сохранён.';
        }
        checked([service,'disable'],5,'Не удалось отключить автозапуск ZRAM');
        return 'ZRAM и его автозапуск выключены.';
    } catch(e){
        // Restore only our fields, preserving administrator edits and other system settings.
        let restore=configuration();
        for(let k,v in next)if(restore.s[k]==v){if(old[k]==null)restore.c.delete('system',restore.name,k);else restore.c.set('system',restore.name,k,old[k]);}
        let restored=restore.c.commit('system');
        command([service,s.enabled?'enable':'disable'],5);
        // Never swapoff during rollback. Restart the former swap only if absent.
        if(restored && s.active && !status().active)command([service,'start'],30);
        die(trim(''+e)+(restored?' Настройки возвращены.':' Не удалось вернуть настройки system.'));
    }
}
const mode=ARGV[0];
if(mode=='status'){
    let s=status(),j=load(run+'/job.json') || {state:'idle'};
    if(j.state=='pending' && time()-j.updated>30 || j.state=='running' && (time()-j.updated>600 || !command(['kill','-0',''+j.pid],2).ok)){
        j={state:'failed',message:'Операция ZRAM была прервана; проверьте состояние.',updated:time()};save(j);
    }
    print(sprintf('%J',{...s,job:j}));exit(0);
}
if(mode=='stage'){
    try{
        let p=validate(json(fs.stdin.read(4097) || '{}'));
        if(!fs.writefile(run+'/request.json',sprintf('%J',p)))die('Не удалось подготовить настройки');
        fs.chmod(run+'/request.json',0600);save({state:'pending',updated:time(),message:'Подготовка ZRAM…'});
    }catch(e){print(sprintf('%J',{error:trim(''+e)}));exit(1);}
    exit(0);
}
if(mode!='worker')die('Unknown operation');
let p=load(run+'/request.json');fs.unlink(run+'/request.json');
let j={state:'running',pid:int(split(fs.readfile('/proc/self/stat'),' ')[0]),updated:time(),message:'Применяем настройки ZRAM…'};save(j);
try{j.message=perform(p);j.state='done';}catch(e){j.message=trim(''+e);j.state='failed';}
j.updated=time();save(j);
