"use strict";
import * as fs from 'fs';
import { cursor } from 'uci';
import { operation_error } from './operation_error.mjs';
export const run_dir = '/var/run/xray-lab-control';
export function quote(v) { return "'" + replace(''+v, /'/g, "'\\''") + "'"; };
export function command(args) { return join(' ',map(args,quote)); };
export function capture(args) {
    let p=fs.popen(command(args)+' 2>/dev/null','r');
    if (!p) return {ok:false,text:''};
    let text=p.read('all') || '', rc=p.close();
    return {ok:rc==0,text,code:rc};
};
// OpenWrt flock implementations share descriptor mode; command mode is optional.
export function operation_lock() {
    let r=capture(['sh','-c',
        'exec 9>"$1" || { printf error; exit; }; if flock -n 9; then printf free; else rc=$?; if [ "$rc" = 1 ]; then printf busy; else printf error; fi; fi',
        'xray-lock-check',run_dir+'/action.lock']);
    let state=trim(r.text);
    return {busy:state=='busy' || state!='free',error:state=='free' || state=='busy' ? null : 'Не удалось проверить блокировку операций'};
};
function parse(s) { try { return json(s); } catch (e) { return null; } }
export function load(path) { return parse(fs.readfile(path) || ''); };
export function save(path,value) {
    fs.mkdir(run_dir,0700);
    if (!fs.writefile(path+'.new',sprintf('%J',value))) die('Cannot write private runtime state');
    fs.chmod(path+'.new',0600);
    if (!fs.rename(path+'.new',path)) die('Cannot commit runtime state');
};
export function config() { let c=cursor(); c.load('xray_core'); return c.get_all('xray_core') || {}; };
export function uptime() { return int(split(fs.readfile('/proc/uptime') || '0',' ')[0]); };
function asjson(args) { let r=capture(args); return r.ok ? parse(r.text) : null; }
function chain(name) { return asjson(['nft','-j','list','chain','inet','fw4',name]); }
function counters(c) {
    let bytes=0,packets=0;
    for (let entry in c?.nftables || []) {
        let rule=entry.rule;
        if (!rule || !length(filter(rule.expr || [], e=>e.tproxy!=null))) continue;
        for (let e in rule.expr || []) if (e.counter) {bytes+=int(e.counter.bytes);packets+=int(e.counter.packets);}
    }
    return {bytes,packets};
};
function mem(field,body) { let m=match(body || '',regexp('(^|[\r\n])'+field+':[[:space:]]+([0-9]+)')); return m?int(m[2])*1024:0; }
export function job() {
    let j=load(run_dir+'/job.json') || {state:'idle'};
    if (j.state=='pending' && !j.pid && time()-j.updated>5) {
        j.state='failed'; j.message='Операция не запустилась. Откройте диагностику.';
    }
    if (index(['pending','running'],j.state)>=0 && j.pid && !fs.stat('/proc/'+j.pid)) {
        j.state='failed'; j.message='Операция прервана. Запустите диагностику.';
    }
    if (j.state=='failed') {
        let text=capture(['tail','-n','25',run_dir+'/job.log']).text;
        let download=match(text,/Subscription download failed: curl=([0-9]+), HTTP=([0-9]+)/);
        if (index(text,'allowInsecure')>=0) j.message='Подписка не применена: устаревший параметр TLS allowInsecure. Рабочая конфигурация сохранена.';
        if (download) j.message='Не удалось обновить подписку: curl='+download[1]+', HTTP='+download[2]+'.';
        if (index(text,'previous selection restored')>=0) j.message='Локация не прошла HTTPS-проверку. Предыдущий выбор восстановлен.';
        j.message=operation_error(text,j.message);
    }
    return j;
};
function positive_number(v) {
    return (type(v)=='int' || type(v)=='double') && v>=0 && v<=9007199254740991 ? v:null;
}
export function subscription() {
    const cached=load('/etc/forkop-xray/subscription.json') || {}, meta=cached.metadata || {};
    const success=positive_number(int(trim(fs.readfile('/var/run/forkop-xray/last-success-update') || '0')));
    const persisted=positive_number(int(trim(fs.readfile('/etc/forkop-xray/last-success-update') || '0')));
    const updated=positive_number(cached.updated) || 0;
    const data=meta.traffic || {};
    let upload=positive_number(data.upload), download=positive_number(data.download), total=positive_number(data.total);
    let traffic=null;
    if (upload!=null || download!=null || total!=null) {
        let used=(upload || 0)+(download || 0);
        traffic={used,total:total>0?total:null,remaining:total>0?max(0,total-used):null,
            unlimited:total==0 || (total==null && data.isUnlimited===true)};
    }
    return {announce:type(meta.announce)=='string' && length(meta.announce)?substr(meta.announce,0,500):null,title:type(meta.title)=='string' && length(meta.title)?substr(meta.title,0,120):null,
        updated:max(success || 0,persisted || 0,updated),expire:positive_number(meta.expire)>0?meta.expire:null,traffic,
        available:length(cached.nodes || [])>0};
};
function list_updated() {
    // Only the small root header is read; list payloads can contain hundreds of thousands of entries.
    let f=fs.open('/etc/forkop-xray/rulesets.json','r');
    if (!f) return null;
    let head=f.read(512) || '';f.close();
    let m=match(head,/^[[:space:]]*\{[[:space:]]*"version"[[:space:]]*:[[:space:]]*1[[:space:]]*,[[:space:]]*"updated"[[:space:]]*:[[:space:]]*([0-9]+)/);
    return m?int(m[1]):null;
};

function update_history(kind) {
    let data=load(run_dir+'/update-'+kind+'.json');
    if (!data) return null;
    if (data.state=='running' &&
        (!data.pid || !fs.stat('/proc/'+data.pid))) {
        data.state='interrupted';
        data.error='Обновление прервано; результат не записан';
    }
    return data;
};

export function snapshot() {
    fs.mkdir(run_dir,0700);
    let version=trim(fs.readfile(run_dir+'/core-version') || '');
    if (!version) {
        version=split(capture(['/usr/libexec/forkop-xray/xray','version']).text,'\n')[0] || '';
        if (version) fs.writefile(run_dir+'/core-version',version);
    }
    const c=config(), g=c.general || {}, now=time(), lock=operation_lock();
    const services=asjson(['ubus','call','service','list','{"name":"xray_core"}']) || {};
    let pid;
    for (let v in values(services.xray_core?.instances || {})) if (v.running) pid=v.pid;
    const metrics=pid ? asjson(['curl','--silent','--fail','--noproxy','*','--max-time','2',
        '--max-filesize','524288','http://127.0.0.1:18889/debug/vars']) : null;
    const pre=chain('xray_prerouting'), post=chain('xray_transparent_proxy'), tp=chain('tp_spec_wan_fw');
    const rules=capture(['ip','-4','rule','show']).text;
    const routes=capture(['ip','-4','route','show','table','251']).text;
    let table_names=['251'];
    for (let path in ['/etc/iproute2/rt_tables','/usr/share/iproute2/rt_tables',...(fs.glob('/etc/iproute2/rt_tables.d/*.conf') || [])])
        for (let line in split(fs.readfile(path) || '', '\n')) {
            const entry=match(line,/^251[[:space:]]+([A-Za-z0-9_-]+)/);
            if (entry) push(table_names,entry[1]);
        }
    let policy=false;
    for (let line in split(rules,'\n')) {
        const entry=match(line,/^104:.*fwmark (0x0*fb|251)(\/0xffffffff)? .*lookup ([A-Za-z0-9_-]+)[[:space:]]*$/);
        if (entry && index(table_names,entry[3])>=0) policy=true;
    }
    const route=match(routes,/(^|[\r\n])local (default|0\.0\.0\.0\/0) dev lo/)!=null;
    function hook(c) { return length(filter(c?.nftables || [], e=>e.chain?.hook=='prerouting'))>0; }
    let ports=[];
    for (let entry in tp?.nftables || []) for (let expr in entry.rule?.expr || [])
        if (expr.tproxy?.family=='ip') push(ports,int(expr.tproxy.port));
    const tproxy=index(ports,int(g.tproxy_port_tcp_v4 || 1082))>=0 && index(ports,int(g.tproxy_port_udp_v4 || 1084))>=0;
    let iface=g.fx_watch_interface || 'lan';
    if (!match(iface,/^[A-Za-z0-9_-]{1,32}$/)) iface='lan';
    const watched=asjson(['ubus','call','network.interface.'+iface,'status']) || {};
    const lan=asjson(['ubus','call','network.interface.lan','status']) || {};
    const bi=pid && metrics ? asjson(['/usr/libexec/forkop-xray/xray','api','bi','--timeout=1','--json','fx_main']) : null;
    const override=bi?.balancer?.override?.target;
    const auto_info=override=='fx_auto'?asjson(['/usr/libexec/forkop-xray/xray','api','bi','--timeout=1','--json','fx_auto_pool']):null;
    const chosen=auto_info || bi;
    const selected=override && override!='fx_auto'?[override]:chosen?.balancer?.principleTarget?.tag || chosen?.balancer?.principle_target?.tag || [];
    let nodes=[];
    const manual=load(run_dir+'/latency.json') || {};
    const runtime=load('/var/etc/xray/config.json') || {};
    for (let key in sort(filter(keys(c),k=>c[k]['.type']=='servers'))) {
        const n=c[key], tag='fx_node:'+key, o=metrics?.observatory?.[tag];
        const tested=manual.nodes?.[key];
        const last=int(o?.last_try_time || o?.lastTryTime || 0);
        const use_manual=tested && manual.core_pid==pid && int(manual.checked)>last;
        let r=use_manual?tested:o;
        const stamp=use_manual?manual.checked:last;
        const fresh=stamp && now-stamp>=0 && now-stamp <= max(180,3*int(g.fx_probe_interval || 60));
        const inbound=filter(runtime.inbounds || [],x=>x.tag=='fx_probe:'+key)[0];
        push(nodes,{id:key,name:n.alias || n.server || key,protocol:n.protocol,
            alive:fresh && r ? r.alive===true : null,rtt_ms:fresh && r?.alive===true ? int(r.delay) : null,
            checked:stamp || 0,source:use_manual?'manual':'observatory',
            selected:index(selected,tag)>=0,probe_port:inbound?.port || null,
            configured:g.fx_mode=='auto' || g.fx_location==key});
    }
    let upload=0,download=0,lan_upload=0,lan_download=0;
    for (let tag,v in metrics?.stats?.inbound || {}) if (index(['tproxy_tcp_inbound_v4','tproxy_udp_inbound_v4','socks_inbound'],tag)>=0) {
        upload+=int(v.uplink); download+=int(v.downlink);
        if (tag!='socks_inbound') {lan_upload+=int(v.uplink);lan_download+=int(v.downlink);}
    }
    let memory=fs.readfile('/proc/meminfo') || '', proc=pid?fs.readfile('/proc/'+pid+'/status'):'';
    const health=load(run_dir+'/health.json');
    let flow_offloading=null;
    try {
        let f=cursor();f.load('firewall');
        let defaults=filter(values(f.get_all('firewall') || {}),v=>v['.type']=='defaults')[0];
        if (defaults) flow_offloading=defaults.flow_offloading=='1' || defaults.flow_offloading_hw=='1';
    } catch(e) {}
    const diagnostic=load(run_dir+'/diagnostics.json') || {};
    const routing=g.fx_routing=='roscomvpn'?(load('/usr/share/xray/roscomvpn/profile.json') || {}):{};
    return {version:'1.2.0-r3',selection_history:load(run_dir+'/selection-events.json')?.events || [],routing:{profile:g.fx_routing || 'all-proxy',updated:positive_number(routing._router_updated),upstream:positive_number(int(routing.LastUpdated)),geoip_version:match(routing.Geoipurl || '',/@([0-9]{12})\//)?.[1] || null,geosite_version:match(routing.Geositeurl || '',/@([0-9]{12})\//)?.[1] || null},diagnostics_checked:diagnostic.checked || null,diagnostics_summary:{job_id:diagnostic.job_id,errors:length(filter(diagnostic.checks || [],c=>c.state=='error')),pending:length(filter(diagnostic.checks || [],c=>c.state=='pending'))},subscription:subscription(),updates:{lists:list_updated(),subscription:update_history('subscription'),routing:update_history('routing')},time:now,uptime:uptime(),enabled:g.transparent_proxy_enable=='1',
        mode:g.fx_mode || 'manual',location:g.fx_location || '',core:{running:pid!=null,pid:pid || null,version,
            rss:mem('VmRSS',proc),peak:mem('VmHWM',proc)},
        memory:{total:mem('MemTotal',memory),available:mem('MemAvailable',memory)},flow_offloading,
        interception:{prerouting:hook(pre),transparent_hook:hook(post),tproxy,policy,route,
            active:pid!=null && hook(pre) && hook(post) && tproxy && policy && route,
            counters:counters(tp)},
        metrics_ready:metrics!=null,autostart:capture(['/etc/init.d/xray_core','enabled']).ok,
        nodes,traffic:{upload,download,lan_upload,lan_download},
        interface:{name:iface,up:watched.up===true,device:watched.l3_device || watched.device || '',
            signature:sprintf('%J',{up:watched.up,device:watched.l3_device,
                addresses:map(watched['ipv4-address'] || [],a=>({address:a.address,mask:a.mask})),
                route:map(watched.route || [],r=>({target:r.target,mask:r.mask,nexthop:r.nexthop,metric:r.metric,source:r.source}))})},
        lan:{device:lan.l3_device || g.lab_iface,address:lan['ipv4-address']?.[0]?.address || g.lab_address},
        health:health && health.proxy_pid==pid && now-health.checked>=0 && now-health.checked<=90 ? health:null,
        watchdog:load(run_dir+'/watchdog.json') || {reason:'not_started'},job:job(),
        operation_busy:lock.busy,operation_lock_error:lock.error,
        model:trim(fs.readfile('/tmp/sysinfo/model') || ''),load:split(fs.readfile('/proc/loadavg') || '',' ')[0]};
};
function direct_resolve(url) {
    const endpoint=match(url,/^https:\/\/([A-Za-z0-9_.-]+)(:([0-9]+))?([\/;?#]|$)/);
    if (!endpoint) return null;
    const host=endpoint[1], port=endpoint[3] || '443';
    if (match(host,/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/)) return [];
    // Router DNS is proxied. A failed tunnel must not also break the direct
    // control probe and masquerade as a provider outage.
    const answer=capture(['nslookup','-type=A','-timeout=3','-retry=1',host,'1.1.1.1']);
    let named=false;
    for (let line in split(answer.text,'\n')) {
        if (match(line,/^Name:/)) named=true;
        const address=named?match(line,/^Address([[:space:]][0-9]+)?:[[:space:]]+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/):null;
        if (address) return ['--resolve',host+':'+port+':'+address[2]];
    }
    return null;
}
export function probe(port,url) {
    let args=['curl','--silent','--connect-timeout','5','--max-time','10','--proto','=https',
        '--noproxy',port?'':'*','--output',run_dir+'/probe.body','--write-out','%{http_code} %{time_total}'];
    if (port) push(args,'--proxy','socks5h://127.0.0.1:'+port);
    else {
        const resolver=direct_resolve(url);
        if (resolver==null) return {alive:false,delay:0,http:'000',error:'bootstrap_dns'};
        push(args,...resolver);
    }
    push(args,url);
    const r=capture(args), parts=split(trim(r.text),' ');
    fs.unlink(run_dir+'/probe.body');
    const elapsed=match(parts[1] || '',/^[0-9]+\.[0-9]+$/)?json(parts[1]):0;
    return {alive:r.ok && parts[0]=='204',delay:int(elapsed*1000),http:parts[0] || '000',curl:r.code};
};
export function health_check() {
    const g=config().general || {}, url=g.fx_probe_url || 'https://cp.cloudflare.com/generate_204';
    if (!match(url,/^https:\/\/[^[:space:]]+$/)) die('Invalid HTTPS probe URL');
    fs.mkdir(run_dir,0700);
    const proxy=probe(1080,url), direct=proxy.alive?null:probe(null,url);
    const result={checked:time(),proxy_ok:proxy.alive,delay:proxy.delay,http:proxy.http,
        direct_ok:direct?.alive===true,direct_error:direct?.error || null,proxy_pid:snapshot().core.pid};
    save(run_dir+'/health.json',result); return result;
};
export function latencies() {
    const s=snapshot(), g=config().general || {}, nodes={};
    for (let n in s.nodes) nodes[n.id]=n.probe_port ? probe(n.probe_port,g.fx_probe_url || 'https://cp.cloudflare.com/generate_204') : {alive:false,delay:0,http:'000'};
    const result={checked:time(),core_pid:s.core.pid,nodes}; save(run_dir+'/latency.json',result); return result;
};
export function diagnose() {
    const s=snapshot(), checks=[];
    let result={started:time(),checked:null,running:true,stage:'core',completed_groups:[],checks,
        completed:0,total:20+length(s.nodes),job_id:job().id || null};
    function publish() { result.completed=length(checks); save(run_dir+'/diagnostics.json',result); }
    function stage(name) {
        if (result.stage && result.stage!=name && index(result.completed_groups,result.stage)<0) push(result.completed_groups,result.stage);
        result.stage=name; publish();
    }
    function add(value) { push(checks,value); publish(); }
    function check(group,title,ok,detail) { add({group,title,state:ok?'ok':'error',detail}); }
    publish();
    check('core','Процесс xtlsproVPN',s.core.running,s.core.running?'PID '+s.core.pid:'Служба остановлена');
    check('core','Версия xtlsproVPN',!!s.core.version,s.core.version || 'Не определена');
    const validation=capture(['env','GOMEMLIMIT=128MiB','/usr/libexec/forkop-xray/xray','run','-test','-c','/var/etc/xray/config.json']);
    check('core','Конфигурация xtlsproVPN',validation.ok,validation.ok?'Проверка ядром пройдена':'Конфигурация отсутствует или отклонена ядром');
    for (let kind,title in {subscription:'Последнее обновление подписки',routing:'Последнее обновление маршрутизации'}) {
        const update=s.updates?.[kind];
        if (update?.state=='error') add({group:'core',title,state:'error',detail:(update.error || 'Обновление не применено.')+' Проверка работающего прокси выполняется отдельно.'});
    }
    stage('interface');
    check('interface','Наблюдаемый интерфейс',s.interface.up,s.interface.name+' / '+s.interface.device);
    const gateway=capture(['ip','-4','route','show','default']);
    check('interface','Маршрут по умолчанию',gateway.ok && length(trim(gateway.text))>0,
        trim(gateway.text) || 'Маршрут не найден');
    stage('firewall');
    add({group:'firewall',title:'Flow offloading',state:s.flow_offloading===false?'ok':s.flow_offloading===true?'error':'pending',
        detail:s.flow_offloading===false?'Выключен':s.flow_offloading===true?'Выключите ускорение потоков в настройках firewall: оно может обходить перехват.':'Не удалось определить настройку firewall.'});
    for (let key,title in {prerouting:'Цепочка маркировки LAN',transparent_hook:'Цепочка перехвата LAN',tproxy:'Правила TPROXY для TCP и UDP',policy:'Правило fwmark 251',route:'Локальный маршрут таблицы 251'})
        check('firewall',title,s.interception[key],s.interception[key]?'Установлено':'Отсутствует');
    check('firewall','Проксирование разрешено',s.enabled,s.enabled?'Включено':'Выключено');
    stage('dns');
    for (let address,title in {'127.0.0.1:53':'DNS на роутере','127.0.0.1:5300':'DNS xtlsproVPN (через прокси)','1.1.1.1':'Bootstrap DNS напрямую'}) {
        const r=capture(['nslookup','-type=A','-timeout=3','-retry=1','openwrt.org',address]);
        const ok=r.ok && match(r.text,/(^|[\r\n])Name:/)!=null;
        check('dns',title,ok,ok?'Ответ получен':'Нет ответа DNS');
    }
    add({group:'dns',title:'FakeDNS / IPv6',state:'info',detail:'Текущий IPv4-профиль использует обычный DNS. FakeDNS и проксирование IPv6 не включены.'});
    stage('outbounds');
    const h=health_check();
    check('outbounds','HTTPS через локальный SOCKS',h.proxy_ok,'HTTP '+h.http+', '+h.delay+' мс');
    const g=config().general || {}, nodes={};
    for (let n in s.nodes) {
        result.current=n.name; publish();
        let r=n.probe_port?probe(n.probe_port,g.fx_probe_url || 'https://cp.cloudflare.com/generate_204'):{alive:false,http:'000'};
        nodes[n.id]=r;
        check('outbounds',n.name,r.alive,r.alive?r.delay+' мс':'HTTP '+r.http+' / curl='+(r.curl ?? 'нет данных')+' / соединение не прошло');
    }
    save(run_dir+'/latency.json',{checked:time(),core_pid:s.core.pid,nodes});
    result.current=null;stage('client');
    const ipargs=['curl','--silent','--fail','--connect-timeout','4','--max-time','8','--proto','=https'];
    const proxy_ip=capture([...ipargs,'--noproxy','','--proxy','socks5h://127.0.0.1:1080','https://api.ipify.org']);
    const resolver=direct_resolve('https://api.ipify.org');
    const direct_ip=resolver==null?{ok:false,text:''}:capture([...ipargs,'--noproxy','*',...resolver,'https://api.ipify.org']);
    function ip(r) {let v=trim(r.text);return r.ok && match(v,/^[0-9a-fA-F:.]{3,45}$/)?v:null;}
    add({group:'client',title:'Трафик LAN через xtlsproVPN',
        state:s.traffic.lan_upload+s.traffic.lan_download>0?'ok':'info',
        detail:s.traffic.lan_upload+s.traffic.lan_download>0?'Получены байты на TPROXY-входах':'Откройте сайт на клиенте со шлюзом и DNS '+s.lan.address+'; затем повторите проверку.'});
    add({group:'client',title:'Выходной IP',state:ip(proxy_ip)?'ok':'error',
        detail:'Прокси: '+(ip(proxy_ip) || 'не получен')+'; напрямую: '+(ip(direct_ip) || 'не получен')});
    add({group:'client',title:'IP клиента в браузере',state:'info',
        detail:'Для сайта, который профиль направляет через прокси, IP клиента должен соответствовать выбранному узлу. DIRECT-сайты могут показывать IP провайдера. Шлюз и DNS клиента: '+s.lan.address});
    push(result.completed_groups,'client');result.stage=null;result.running=false;result.checked=time();
    result.proxy_ip=ip(proxy_ip);result.direct_ip=ip(direct_ip);
    result.total=length(checks);publish();return result;
};
export function redacted_logs() {
    let text=capture(['tail','-n','40','/var/log/xray-lab-error.log']).text;
    // Never expose credentials/configuration through the diagnostic endpoint.
    text=replace(text,/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g,'<UUID>');
    text=replace(text,/(https?|vless):\/\/[^[:space:]"']+/g,'<URL>');
    text=replace(text,/(mlkem768x25519plus\.[^[:space:]"']+)/g,'<MLKEM>');
    text=replace(text,/[A-Za-z0-9_-]{43,}/g,'<KEY>');
    return {text:substr(text,-12000)};
};
