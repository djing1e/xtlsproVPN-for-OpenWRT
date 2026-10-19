#!/usr/bin/ucode
import * as fs from 'fs';
import { cursor } from 'uci';
import { rescue_decide } from '/usr/share/xray/lab/rescue_policy.mjs';
const RUN='/var/run/xtlspro-rescue';
const ID='/etc/xtlspro-rescue/id_ed25519';
const KNOWN='/root/.ssh/known_hosts';
const SERVICE='/etc/init.d/xray_rescue_tunnel';
const WATCH='/etc/init.d/xray_rescue_watch';
function quote(v){return "'"+replace(''+v,/'/g,"'\\''")+"'";}
function capture(args,seconds){
    let p=fs.popen(join(' ',map(['timeout','-k','2',''+(seconds || 4),...args],quote))+' 2>/dev/null','r');
    if(!p)return {ok:false,text:''};
    let text=p.read('all') || '';return {ok:p.close()==0,text};
}
function parse(s){try{return json(s);}catch(e){return null;}}
function write(path,text,mode){
    let f=fs.open(path+'.new','w',mode || 0600);if(!f)die('Не удалось записать состояние аварийного SSH');
    let ok=f.write(text);f.close();
    if(!ok || !fs.rename(path+'.new',path))die('Не удалось сохранить состояние аварийного SSH');
}
function state(){return parse(fs.readfile(RUN+'/state.json') || '') || {};}
function save(s){write(RUN+'/state.json',sprintf('%J',s));}
function config(){return cursor().get_all('xray_lab_rescue','main') || {};}
function ipv4(v){
    if(type(v)!='string' || !match(v,/^[0-9]{1,3}(\.[0-9]{1,3}){3}$/))return false;
    let p=split(v,'.');return !length(filter(p,x=>int(x)>255 || ''+int(x)!=x)) && int(p[0])>0 && int(p[0])!=127 && int(p[0])<224;
}
function validate(p){
    if(type(p)!='object' || !ipv4(p.host))die('Укажите IPv4-адрес сервера аварийного SSH');
    let s={host:p.host,user:p.user,host_key:trim(p.host_key || '')};
    if(match(s.host_key,/[\r\n]/))die('Публичный ключ сервера должен быть одной строкой');
    if(type(s.user)!='string' || !match(s.user,/^[a-z_][a-z0-9_-]{0,31}$/) || s.user=='root')die('Используйте отдельного непривилегированного пользователя туннеля');
    for(let k in ['port','remote_port','local_port']){
        let v=''+p[k];if(!match(v,/^[0-9]{1,5}$/) || int(v)<(k=='remote_port'?1024:1) || int(v)>65535)die('Недопустимый TCP-порт');
        s[k]=''+int(v);
    }
    let m=match(s.host_key,/^ssh-ed25519[[:space:]]+(AAAAC3NzaC1lZDI1NTE5AAAAI[A-Za-z0-9+\/]{43})([[:space:]]+[^\r\n]*)?$/);
    if(!m)die('Вставьте публичный ключ сервера ssh-ed25519, полученный через доверенный доступ');
    s.host_key='ssh-ed25519 '+m[1];return s;
}
function public_key(){
    if(!fs.stat(ID))return '';
    let r=capture(['dropbearkey','-y','-f',ID],3);
    return r.ok?match(r.text,/(ssh-ed25519 [A-Za-z0-9+\/]+)/)?.[1] || '':'';
}
function pin(s){
    let contents=fs.readfile(KNOWN) || '',entry=s.host+' '+s.host_key;
    let found=false;
    for(let line in split(contents,'\n')){
        let m=match(line,/^([^[:space:]]+)[[:space:]]+([^[:space:]]+)[[:space:]]+([^[:space:]]+)/);
        if(m?.[1]!=s.host)continue;
        if(s.host+' '+m[2]+' '+m[3]!=entry)die('В known_hosts уже есть другой ключ сервера; проверьте его вручную');
        found=true;
    }
    fs.mkdir('/root/.ssh',0700);
    if(!found)write(KNOWN,contents+'\n'+entry+'\n');
    fs.chmod(KNOWN,0600);
}
function process(){
    let r=capture(['ubus','call','service','list','{"name":"xray_rescue_tunnel"}'],3);
    let d=r.ok?parse(r.text):null;
    for(let name,v in d?.xray_rescue_tunnel?.instances || {}){
        let pid=int(v.pid || 0),cmd=fs.readfile('/proc/'+pid+'/cmdline') || '';
        if(!v.running || pid<2 || index(cmd,'dbclient')<0 || index(cmd,ID)<0)continue;
        let sockets=[];
        for(let fd in fs.glob('/proc/'+pid+'/fd/*') || []){
            let m=match(fs.readlink(fd) || '',/^socket:\[([0-9]+)\]$/);if(m)push(sockets,m[1]);
        }
        let established=false;
        for(let row in split(fs.readfile('/proc/net/tcp') || '','\n')){
            let cells=split(trim(row),/[[:space:]]+/);
            if(cells[3]=='01' && index(sockets,cells[9])>=0)established=true;
        }
        let rss=match(fs.readfile('/proc/'+pid+'/status') || '',/VmRSS:[[:space:]]*([0-9]+)/)?.[1];
        return {pid,established,rss_bytes:int(rss || 0)*1024};
    }
    return {pid:null,established:false,rss_bytes:0};
}
function plan(s){
    s=validate(s);
    if(!fs.stat(ID) || (fs.stat(ID).mode & 0077))die('Нужен приватный ключ роутера с правами 0600');
    if(!fs.stat('/usr/bin/dbclient'))die('Не установлен клиент Dropbear dbclient');
    if(cursor().get_all('xray_lab_dns','main')?.output_enabled=='1')die('Аварийный SSH пока не поддерживает перехват OUTPUT; отключите его перед настройкой резерва');
    let main=capture(['ip','-4','route','show','table','main','default'],3);
    let device=match(main.text,/[[:space:]]dev[[:space:]]+([A-Za-z0-9_.:-]+)/)?.[1];
    let route=capture(['ip','-j','-4','route','get',s.host],3),r=route.ok?parse(route.text)?.[0]:null;
    if(!device || r?.dev!=device || !ipv4(r?.prefsrc))die('Нет прямого IPv4-маршрута к серверу через основной uplink');
    pin(s);
    let args=['/usr/bin/dbclient','-N','-T','-K','30','-b',r.prefsrc,
        '-o','BatchMode=yes','-o','PasswordAuthentication=no','-o','StrictHostKeyChecking=yes',
        '-o','ExitOnForwardFailure=yes','-i',ID,'-p',s.port,
        '-R','127.0.0.1:'+s.remote_port+':127.0.0.1:'+s.local_port,s.user+'@'+s.host];
    write(RUN+'/command.sh','set -- '+join(' ',map(args,quote))+'\n',0600);
    return args;
}
function status(){
    let s=config(),p=process();
    return {enabled:s.enabled=='1',host:s.host || '',port:s.port || '22',user:s.user || 'xtls-rescue',
        remote_port:s.remote_port || '22001',local_port:s.local_port || '22',host_key:s.host_key || '',
        public_key:public_key(),client_available:!!fs.stat('/usr/bin/dbclient'),
        process:p,state:state()};
}
function tick(){
    let cfg=config(),p=process(),s=state(),now=int(split(fs.readfile('/proc/uptime') || '0',' ')[0]);
    let previous_reason=s.reason;
    let enabled=capture(['/etc/init.d/netbird','enabled'],2).ok || capture(['/etc/init.d/netbird-wrapper','enabled'],2).ok;
    let d=enabled?parse(capture(['/usr/bin/netbird','status','--json'],4).text):null;
    let next=rescue_decide(s,{enabled:cfg.enabled=='1',running:!!p.pid,established:p.established,
        netbird_enabled:enabled,manual_down:d?.daemonStatus=='Idle',
        healthy:d?.management?.connected===true && !!d?.netbirdIp && d?.signal?.connected!==false},now);
    next.checked=time();
    if(next.action=='start'){
        save(next);
        try{plan(cfg);if(!capture([SERVICE,'start'],8).ok)die('Служба туннеля не запустилась');next.error=null;}
        catch(e){next.reason='start_failed';next.error=trim(''+e);}
    } else if(next.action=='stop')capture([SERVICE,'stop'],8);
    if(previous_reason!=next.reason)capture(['logger','-t','xray-rescue','Emergency SSH: '+next.reason],2);
    save(next);
}
try{
    let mode=ARGV[0];
    if(mode=='status'){print(sprintf('%J',status()));exit(0);}
    if(mode=='tick'){tick();exit(0);}
    if(mode!='action')die('Unknown mode');
    let p=parse(fs.stdin.read(4097) || ''),action=p?.action;
    if(index(['configure','generate','open','close','disable'],action)<0)die('Недопустимое действие аварийного SSH');
    if(action=='generate'){
        fs.mkdir('/etc/xtlspro-rescue',0700);fs.chmod('/etc/xtlspro-rescue',0700);
        if(!fs.stat(ID) && !capture(['dropbearkey','-t','ed25519','-f',ID],10).ok)die('Не удалось создать ключ роутера');
        fs.chmod(ID,0600);
        if(!public_key())die('Не удалось прочитать публичный ключ роутера');
    } else if(action=='configure'){
        let v=validate(p);pin(v);
        capture([SERVICE,'stop'],8);
        let c=cursor();c.set('xray_lab_rescue','main','rescue');
        for(let k,val in {...v,enabled:'1'})c.set('xray_lab_rescue','main',k,val);
        if(!c.commit('xray_lab_rescue'))die('Не удалось сохранить настройки');
        fs.chmod('/etc/config/xray_lab_rescue',0600);
        save({});
        if(!capture([WATCH,'enable'],3).ok || !capture([WATCH,'start'],5).ok)die('Не удалось включить наблюдение аварийного SSH');
    } else if(action=='disable'){
        let c=cursor();c.set('xray_lab_rescue','main','enabled','0');
        if(!c.commit('xray_lab_rescue'))die('Не удалось отключить резерв');
        capture([WATCH,'disable'],3);capture([WATCH,'stop'],8);capture([SERVICE,'stop'],8);
        save({reason:'disabled'});
    } else {
        let s=state(),now=int(split(fs.readfile('/proc/uptime') || '0',' ')[0]);
        if(action=='open'){
            if(config().enabled!='1')die('Сначала сохраните и включите настройки резерва');
            plan(config());s.manual_until=now+1800;s.pause_until=0;s.retry_at=0;
        }else{s.manual_until=0;s.pause_until=now+1800;}
        save(s);tick();
    }
    print('{"ok":true}');
}catch(e){print(sprintf('%J',{error:trim(''+e)}));exit(1);}
