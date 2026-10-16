#!/usr/bin/ucode
import * as fs from 'fs';
import { cursor } from 'uci';

const RUN='/var/run/xtlspro-netbird';
const BIN='/usr/bin/netbird';
const SERVICE='/etc/init.d/netbird';
const GUARD='/etc/init.d/xray_netbird_guard';
const CONFIG='xray_lab_netbird';
function quote(v) {return "'"+replace(''+v,/'/g,"'\\''")+"'";}
function capture(args,seconds,stderr) {
    let command=join(' ',map(['timeout','-k','5',''+(seconds || 5),...args],quote));
    let p=fs.popen(command+(stderr?' 2>&1':' 2>/dev/null'),'r');
    if (!p) return {ok:false,text:''};
    let text=p.read('all') || '', rc=p.close();
    return {ok:rc==0,text,code:rc};
}
function parse(s) {try {return json(s);} catch(e) {return null;}}
function load(path) {return parse(fs.readfile(path) || '');}
function save(path,value) {
    let f=fs.open(path+'.new','w',0600);
    if (!f) die('Не удалось записать состояние NetBird');
    let ok=f.write(sprintf('%J',value)); f.close();
    if (!ok || !fs.rename(path+'.new',path)) die('Не удалось сохранить состояние NetBird');
}
function settings() {return cursor().get_all(CONFIG,'main') || {};}
function validate(p) {
    if (type(p)!='object') die('Недопустимые параметры');
    let url=p.management_url, host=p.hostname || '', key=p.setup_key || '';
    // No credentials, query strings or shell syntax in a management endpoint.
    let m=type(url)=='string' ? match(url,/^https:\/\/([A-Za-z0-9][A-Za-z0-9.-]*)(:([0-9]{1,5}))?(\/[A-Za-z0-9._~\/%-]*)?$/) : null;
    if (!m || length(url)>512 || match(m[1],/[.-]$/) || (m[3] && (int(m[3])<1 || int(m[3])>65535)))
        die('Укажите HTTPS-адрес self-hosted сервера без логина, пароля и параметров запроса');
    if (type(host)!='string' || (host && !match(host,/^[A-Za-z0-9][A-Za-z0-9-]{0,62}$/)))
        die('Имя устройства: до 63 латинских букв, цифр и дефисов');
    // musl limits bounded regex repetitions to 255; check length separately.
    if (type(key)!='string' || (key && (length(key)<16 || length(key)>256 || !match(key,/^[A-Za-z0-9_-]+$/))))
        die('Недопустимый setup key');
    return {management_url:url,hostname:host,setup_key:key};
}
function daemon_status() {
    if (!fs.stat(BIN)) return null;
    let r=capture([BIN,'status','--json'],4);
    return r.ok ? parse(r.text) : null;
}
function endpoint(url) {return replace(replace(url || '',/\/$/,''),/:443$/,'');}
function require_setup_key(p) {
    if (p.setup_key) return;
    let s=settings();
    if (s.registered_url && endpoint(s.registered_url)==endpoint(p.management_url)) return;
    let d=daemon_status();
    if (d?.management?.connected===true && d?.netbirdIp &&
        endpoint(d.management.url)==endpoint(p.management_url)) return;
    die('Для первой регистрации на этом сервере заполните Setup key. Вход через браузер из этой вкладки не поддерживается.');
}
function resources() {
    let result={binary_bytes:fs.stat(BIN)?.size || 0,rss_bytes:0,pid:null};
    let pids=split(trim(capture(['pidof','netbird'],2).text),' ');
    for (let pid in pids) {
        if (!match(pid,/^[0-9]+$/)) continue;
        let cmd=join(' ',split(fs.readfile('/proc/'+pid+'/cmdline') || '', '\x00'));
        if (index(cmd,'service run')<0) continue;
        let mem=match(fs.readfile('/proc/'+pid+'/status') || '',/VmRSS:[[:space:]]*([0-9]+)/);
        result.pid=int(pid);result.rss_bytes=int(mem?.[1] || 0)*1024;break;
    }
    return result;
}
function job() {
    let j=load(RUN+'/job.json') || {state:'idle'};
    if (j.state=='running' && !capture(['kill','-0',''+j.pid],2).ok ||
        j.state=='pending' && time()-j.updated>30) {
        fs.unlink(RUN+'/request.json');fs.unlink(RUN+'/setup.key');
        j={state:'failed',action:j.action,updated:time(),message:'Операция NetBird была прервана. Повторите действие.'};
        save(RUN+'/job.json',j);
    }
    return j;
}
function status() {
    let s=settings(), d=daemon_status(), j=job();
    return {installed:!!fs.stat(BIN),enabled:capture([SERVICE,'enabled'],2).ok,
        management_url:s.management_url || '',hostname:s.hostname || '',
        active_management_url:d?.management?.url || '',
        registered:!!s.registered_url && endpoint(s.registered_url)==endpoint(s.management_url) ||
            d?.management?.connected===true && !!d?.netbirdIp,
        connected:d?.management?.connected===true,
        netbird_ip:d?.netbirdIp || '',fqdn:d?.fqdn || '',
        management_connected:d?.management?.connected===true,
        signal_connected:d?.signal?.connected===true,
        version:d?.daemonVersion || d?.cliVersion || '',resources:resources(),job:j,
        firewall_mode:s.firewall_mode || 'not_configured',
        dns_managed:false,client_routes:false,server_routes:false};
}
function checked(args,seconds,message) {
    if (!capture(args,seconds).ok) die(message);
}
function login_failure(result,has_key) {
    let text=lc(result.text || '');
    let reason='Не удалось подключиться; проверьте журнал службы NetBird';
    if (result.code==124 || result.code==137 || match(text,/context deadline|timed out|i\/o timeout/))
        reason='Истекло время ожидания сервера NetBird';
    else if (match(text,/lookup|no such host|name resolution/))
        reason='Не удалось разрешить DNS-имя сервера NetBird';
    else if (match(text,/x509|certificate|tls handshake/))
        reason='Ошибка проверки TLS-сертификата сервера NetBird';
    else if (match(text,/setup.?key|permission.?denied|unauthenticated|unauthorized|invalid.?key/))
        reason='Сервер отклонил регистрацию: проверьте setup key, срок действия и лимит использований';
    else if (match(text,/connection refused|unavailable|no route to host|network is unreachable/))
        reason='Сервер NetBird недоступен по сети';
    else if (match(text,/unknown flag|unknown command|flag needs an argument/))
        reason='Установленный клиент NetBird не принял параметры команды';
    else if (!has_key && match(text,/sso|login|authentication/))
        reason='Для регистрации устройства требуется setup key';
    // Classify stderr without exporting raw login output, keys or SSO tokens.
    return reason+' (код '+result.code+').';
}
function words(v) {return type(v)=='array'?v:split(v || '',/[[:space:]]+/);}
function access_firewall() {
    let c=cursor(), all=c.get_all('firewall') || {}, net=c.get_all('network') || {};
    let own=['xtlspro_netbird','xtlspro_netbird_admin'];
    for (let id in own)
        if (all[id] && all[id].xtlspro_managed!='1')
            die('Имя раздела firewall занято чужой конфигурацией');
    // Existing zones remain the administrator's responsibility; never attach
    // an interface to two zones or widen an already configured policy.
    for (let id,zone in all) {
        if (zone['.type']!='zone' || id==own[0]) continue;
        let found=index(words(zone.device),'wt0')>=0;
        for (let n in words(zone.network))
            if ((net[n]?.device || net[n]?.ifname)=='wt0') found=true;
        if (found) return 'existing';
    }
    for (let id in own) c.delete('firewall',id);
    c.set('firewall',own[0],'zone');
    for (let key,value in {name:'xtls_nb',device:['wt0'],input:'REJECT',output:'ACCEPT',forward:'REJECT',xtlspro_managed:'1'})
        c.set('firewall',own[0],key,value);
    c.set('firewall',own[1],'rule');
    for (let key,value in {name:'xtlsproVPN administrator access',src:'xtls_nb',proto:'tcp',dest_port:'22 80 443',target:'ACCEPT',xtlspro_managed:'1'})
        c.set('firewall',own[1],key,value);
    if (!c.commit('firewall')) die('Не удалось сохранить firewall');
    if (!capture(['/etc/init.d/firewall','reload'],30).ok) {
        for (let id in own) {
            c.delete('firewall',id);
            if (all[id]) {
                c.set('firewall',id,all[id]['.type']);
                for (let k,v in all[id]) if (substr(k,0,1)!='.') c.set('firewall',id,k,v);
            }
        }
        c.commit('firewall');capture(['/etc/init.d/firewall','reload'],30);
        die('Firewall не применён; изменения наших разделов отменены');
    }
    return 'managed';
}
function perform(action,p) {
    if (action=='install') {
        if (fs.stat(BIN)) return 'NetBird уже установлен. Конфигурация не изменялась.';
        checked(['apk','update'],120,'Не удалось обновить список пакетов OpenWrt');
        checked(['apk','add','netbird'],300,'Не удалось установить NetBird из репозитория OpenWrt');
        if (!fs.stat(BIN) || !fs.stat(SERVICE)) die('Установка NetBird не завершилась');
        return 'NetBird установлен. Укажите сервер и подключите устройство.';
    }
    if (!fs.stat(BIN) || !fs.stat(SERVICE)) die('Сначала установите NetBird');
    if (action=='disconnect') {
        // Keep the enrolled peer and its identity; a deliberate stop persists.
        checked([GUARD,'disable'],5,'Не удалось выключить автозапуск наблюдения NetBird');
        checked([GUARD,'stop'],10,'Не удалось остановить наблюдение NetBird');
        checked([SERVICE,'disable'],5,'Не удалось выключить автозапуск NetBird');
        capture([BIN,'down'],15);
        checked([SERVICE,'stop'],15,'Не удалось остановить NetBird');
        let c=cursor();c.set(CONFIG,'main','enabled','0');
        if (!c.commit(CONFIG)) die('Не удалось сохранить отключение NetBird');
        return 'NetBird остановлен, автозапуск выключен. Регистрация сохранена.';
    }
    p=validate(p);
    require_setup_key(p);
    let help=capture([BIN,'up','--help'],5);
    for (let flag in ['--disable-dns','--disable-client-routes','--disable-server-routes','--interface-name','--allow-server-ssh','--setup-key-file','--disable-auto-connect'])
        if (!help.ok || index(help.text,flag)<0) die('Установленная версия NetBird не поддерживает необходимые параметры. Обновите пакет NetBird.');
    checked([SERVICE,'start'],15,'Не удалось запустить службу NetBird');
    // 'up' on an already connected daemon can silently ignore new settings.
    checked([BIN,'down'],15,'Не удалось подготовить NetBird к применению настроек');
    let args=[BIN,'up','--management-url',p.management_url,
        '--disable-dns=true','--disable-client-routes=true','--disable-server-routes=true',
        '--allow-server-ssh=false','--interface-name','wt0','--disable-auto-connect=false'];
    if (p.hostname) push(args,'--hostname',p.hostname);
    if (p.setup_key) {
        let key=fs.open(RUN+'/setup.key','w',0600);
        if (!key || !key.write(p.setup_key)) die('Не удалось подготовить setup key');
        key.close();push(args,'--setup-key-file',RUN+'/setup.key');
    }
    // Output is deliberately discarded: login errors may contain credentials.
    let up=capture(args,90,true);
    fs.unlink(RUN+'/setup.key');
    if (!up.ok) die(login_failure(up,!!p.setup_key));
    let d=daemon_status();
    if (d?.management?.connected!==true || !d?.netbirdIp)
        die('Сервер управления пока не подтвердил подключение. Повторите проверку статуса.');
    let firewall=access_firewall();
    let c=cursor();
    for (let k,v in {enabled:'1',management_url:p.management_url,registered_url:p.management_url,hostname:p.hostname,firewall_mode:firewall}) c.set(CONFIG,'main',k,v);
    if (!c.commit(CONFIG)) die('Не удалось сохранить настройки NetBird');
    checked([SERVICE,'enable'],5,'Не удалось включить автозапуск NetBird');
    checked([GUARD,'enable'],5,'Не удалось включить наблюдение NetBird');
    checked([GUARD,'start'],10,'Не удалось запустить наблюдение NetBird');
    return firewall=='existing' ? 'NetBird подключён. Существующая зона firewall сохранена; проверьте доступ к SSH/LuCI.' :
        'NetBird подключён. SSH/LuCI доступны через адрес NetBird; автозапуск включён.';
}

let mode=ARGV[0], action=ARGV[1];
if (mode=='status') {print(sprintf('%J',status()));exit(0);}
if (index(['install','connect','disconnect'],action)<0) die('Unknown action');
if (mode=='stage') {
    try {
        let p=parse(fs.stdin.read(8193) || '{}');
        p=action=='connect'?validate(p):{};
        if (action=='connect') require_setup_key(p);
        save(RUN+'/request.json',p);
        save(RUN+'/job.json',{state:'pending',action,updated:time(),message:'Операция NetBird запускается…'});
    } catch(e) {print(sprintf('%J',{error:trim(''+e)}));exit(1);}
    exit(0);
}
if (mode!='worker') die('Unknown mode');
let p=load(RUN+'/request.json') || {};
fs.unlink(RUN+'/request.json');
let j={state:'running',action,pid:int(split(fs.readfile('/proc/self/stat'),' ')[0]),updated:time(),message:'Выполняется операция NetBird…'};
save(RUN+'/job.json',j);
try {j.message=perform(action,p);j.state='done';}
catch(e) {j.state='failed';j.message=trim(''+e);}
fs.unlink(RUN+'/setup.key');
j.updated=time();save(RUN+'/job.json',j);
exit(j.state=='done'?0:1);
