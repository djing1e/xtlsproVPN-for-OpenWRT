import * as fs from 'fs';
const RUN='/var/run/xtlspro-bot-updates';
function load(p){try{return json(fs.readfile(p) || '');}catch(e){return null;}}
function fail(c){printf('%J\n',{error:c});exit(1);}
function uuid(v){return type(v)=='string' && length(v)==36 && !!match(v,/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/);}
function version(c,v){return type(v)=='string' && length(v)<64 && (c=='app'?!!match(v,/^[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+$/):c=='xray'?!!match(v,/^[0-9]{1,3}\.[0-9]{1,2}\.[0-9]{1,2}$/):!!match(v,/^[0-9][A-Za-z0-9._+~-]*$/));}
function save(p,d){let f=fs.open(p+'.new','w',0600);if(!f)fail('state_failed');f.write(sprintf('%J',d));f.close();if(!fs.rename(p+'.new',p))fail('state_failed');}
function capture(command){let p=fs.popen('/usr/bin/timeout -k 1 8 '+command+' 2>/dev/null','r');if(!p)return null;let s=p.read(32769),rc=p.close();return rc==0 && length(s || '')<=32768?s:null;}
function installed(c){
    let s=capture(c=='xray'?'/usr/libexec/forkop-xray/xray version':'apk info -v -e '+(c=='app'?'xtlsprovpn':'netbird')) || '';
    let v=c=='xray'?split(trim(s),/[[:space:]]+/)[1]:substr(trim(s),c=='app'?11:8);
    return version(c,v)?v:null;
}
function newer(c,a,b){
    if(!version(c,a) || !version(c,b))return false;
    if(c=='xray'){let x=split(a,'.'),y=split(b,'.');for(let n=0;n<3;n++){if(int(y[n])!=int(x[n]))return int(y[n])>int(x[n]);}return false;}
    return trim(capture("apk version -t '"+a+"' '"+b+"'") || '')=='<';
}
if(ARGV[0]=='patch-netbird'){
    let source=fs.readfile(ARGV[1]);if(!source)fail('native_helper_missing');
    let needle='    let c=package_catalog(true);';
    if(index(source,"getenv('FX_NETBIRD_EXPECTED_VERSION')")<0){
        if(length(split(source,needle))!=2)fail('native_helper_changed');
        source=replace(source,needle,needle+"\n    let expected=getenv('FX_NETBIRD_EXPECTED_VERSION');\n    if (expected && c.available!=expected) die('Каталог NetBird изменился. Проверьте версию заново перед установкой.');");
    }
    if(!fs.writefile(ARGV[2],source))fail('state_failed');exit(0);
}
// Compare DHCP semantics, allowing only the NetBird listener migration.
// Do not exempt the whole file: upstream DNS, leases and LAN settings stay protected.
function canonical(v){
    if(type(v)=='array')return '['+join(',',map(v,canonical))+']';
    if(type(v)=='object')return '{'+join(',',map(sort(keys(v)),k=>sprintf('%J',k)+':'+canonical(v[k])))+'}';
    return sprintf('%J',v);
}
if(ARGV[0]=='dhcp-snapshot' || ARGV[0]=='dhcp-verify'){
    let c=require('uci').cursor();
    if(!c.load('dhcp'))fail('dhcp_unreadable');
    let current=c.get_all('dhcp');
    if(type(current)!='object')fail('dhcp_unreadable');
    if(ARGV[0]=='dhcp-snapshot'){save(ARGV[1],current);exit(0);}
    let before=load(ARGV[1]);if(type(before)!='object')fail('dhcp_snapshot_missing');
    if(canonical(before)==canonical(current))exit(0);
    if(ARGV[2]!='app' || !fs.access('/usr/bin/netbird','x'))fail('settings_changed');
    for(let name,section in before){
        if(section['.type']!='dnsmasq')continue;
        let excluded=section.notinterface;
        excluded=type(excluded)=='array'?excluded:excluded==null?[]:[excluded];
        if(index(excluded,'wt0')<0)section.notinterface=[...excluded,'wt0'];
        section.nonwildcard='1';
    }
    if(canonical(before)!=canonical(current))fail('settings_changed');
    print('DHCP: NetBird DNS listener migration verified\n');exit(0);
}
let boot=trim(fs.readfile('/proc/sys/kernel/random/boot_id') || ''), op=ARGV[0],c=ARGV[1],id=ARGV[2];
let job=load(RUN+'/job.json');if(job?.boot_id!=boot)job=null;
function public_plan(p){return p?{id:p.id,component:p.component,installed:p.installed,available:p.available,
    update_available:p.update_available===true,checked:p.checked,expires:p.expires,source:p.source,
    valid:p.boot_id==boot && p.expires>time()}:null;}
if(op=='status'){
    printf('%J\n',{job:job || {state:'idle'},plans:map(['app','xray','netbird'],k=>public_plan(load(RUN+'/'+k+'.json')))});exit(0);
}
if(index(['app','xray','netbird'],c)<0 || !uuid(id))fail('invalid_request');
if(op=='set'){
    let action=ARGV[3],state=ARGV[4];
    if(index(['check','install'],action)<0 || index(['pending','running','done','failed'],state)<0)fail('invalid_request');
    if(state!='pending' && (job?.id!=id || job?.component!=c || job?.action!=action))fail('job_replaced');
    let d={id,component:c,action,state,boot_id:boot,started:job?.id==id?job.started:time(),updated:time()};
    if(state=='failed' && match(ARGV[5] || '',/^[a-z_]{1,40}$/))d.reason=ARGV[5];
    save(RUN+'/job.json',d);exit(0);
}
if(op=='plan'){
    let cat=c=='app'?load('/var/run/xtlspro-package/catalog.json'):c=='netbird'?load('/var/run/xtlspro-netbird/catalog.json'):load('/var/run/xray-lab-control/core-releases.json');
    if(!cat || time()-cat.checked>1800)fail('catalog_unavailable');
    let target=c=='xray'?filter(cat.releases || [],r=>r.prerelease===false)[0]?.version:c=='app'?cat.version:cat.available;
    if(!version(c,target))fail('catalog_unavailable');
    let current=installed(c), digest=c=='app'?cat.sha256:null, available=newer(c,current,target);
    if(c=='app' && available && (type(digest)!='string' || length(digest)!=64 || !match(digest,/^[a-f0-9]+$/)))fail('catalog_unavailable');
    let p={id,component:c,boot_id:boot,installed:current,available:target,update_available:available,digest,
        checked:time(),expires:time()+1800,source:c=='netbird'?'OpenWrt':c=='xray'?'XTLS/Xray-core':'xtlsproVPN stable'};
    save(RUN+'/'+c+'.json',p);printf('%J\n',public_plan(p));exit(0);
}
if(op=='validate'){
    let p=load(RUN+'/'+c+'.json');
    if(p?.id!=id || p.component!=c || p.boot_id!=boot || p.expires<=time() || p.update_available!==true || !version(c,p.available))fail('plan_expired');
    if(p.installed!=installed(c) || !newer(c,p.installed,p.available))fail('installed_changed');
    printf('%J\n',{version:p.available,digest:p.digest});exit(0);
}
if(op=='verify'){
    let p=load(RUN+'/'+c+'.json');if(p?.id!=id || installed(c)!=p.available)fail('version_mismatch');
    p.installed=p.available;p.update_available=false;save(RUN+'/'+c+'.json',p);exit(0);
}
fail('invalid_request');
