import * as fs from 'fs';
import { cursor } from 'uci';

function reply(data) { printf('%J\n',{schema:1,ok:true,data}); exit(0); }
function fail(code) { printf('%J\n',{schema:1,ok:false,error:{code}}); exit(1); }
function object(v) { return type(v)=='object'; }
function valid_id(v) { return type(v)=='string' && !!match(v,/^cfg[A-Za-z0-9_-]{6}$/) && length(v)==9; }
function invoke(args) {
    // Every argument is a constant or was matched against a closed grammar.
    let p=fs.popen('/usr/bin/timeout -k 2 15 /usr/bin/xray-lab-control '+join(' ',args)+' 2>/dev/null','r');
    if(!p) fail('controller_unavailable');
    let body=p.read(262145),rc=p.close();
    if(rc!=0 || !body || length(body)>262144) fail('controller_failed');
    let d;try{d=json(body);}catch(e){fail('invalid_controller_response');}
    if(!object(d))fail('invalid_controller_response');
    if(d.error)fail('operation_rejected');
    return d;
}
function nonnegative(v) { return (type(v)=='int' || type(v)=='double') && v>=0 && v<=9007199254740991?v:null; }
function subscription(v) {
    let m=type(v?.announce)=='string'?match(v.announce,/^id:[[:space:]]*([0-9]{1,12})$/):null;
    // Never export title/announce text, URL, node list or other metadata.
    return {id:m && m[0]==v.announce?m[1]:null,available:v?.available===true,
        updated:nonnegative(v?.updated),expire:nonnegative(v?.expire),
        used:nonnegative(v?.traffic?.used),total:nonnegative(v?.traffic?.total),
        remaining:nonnegative(v?.traffic?.remaining),unlimited:v?.traffic?.unlimited===true};
}
function job(d) {
    return {id:type(d?.id)=='string'?d.id:null,state:d?.state || 'idle',
        action:d?.action || null,updated:d?.updated || null};
}

try {
    const cmd=getenv('SSH_ORIGINAL_COMMAND') || '';
    if(length(cmd)>120 || index(cmd,'\n')>=0 || index(cmd,'\r')>=0)fail('unsupported_command');
    let op=null,target=null,requested_job=null;
    if(cmd=='xtlsbot-v1 status')op='status';
    else if(cmd=='xtlsbot-v1 locations')op='locations';
    else if(cmd=='xtlsbot-v1 diagnostics')op='diagnostics';
    else if(cmd=='xtlsbot-v1 auto'){op='select';target='auto';}
    else {
        let m=match(cmd,/^xtlsbot-v1 select (cfg[A-Za-z0-9_-]{6})$/);
        if(m && m[0]==cmd){op='select';target=m[1];}
        else {
            m=match(cmd,/^xtlsbot-v1 job ([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/);
            if(m && m[0]==cmd){op='job';requested_job=m[1];}
        }
    }
    if(!op)fail('unsupported_command');
    if(op=='job') {
        let d=invoke(['job']);
        if(d.id!=requested_job)fail('job_replaced');
        reply({job:job(d)});
    }
    let s=invoke(['status']);
    let nodes=filter(s.nodes || [],n=>object(n) && valid_id(n.id));
    let selected=map(filter(nodes,n=>n.selected===true),n=>n.id);
    if(op=='status')reply({version:s.version || null,enabled:s.enabled===true,
        running:s.core?.running===true,mode:s.mode=='auto'?'auto':'manual',
        selected,proxy_ok:s.health?.proxy_ok ?? null,health_checked:s.health?.checked || null,
        operation_busy:s.operation_busy===true,subscription:subscription(s.subscription),job:job(s.job)});
    if(op=='diagnostics')reply({uptime:nonnegative(s.uptime),
        running:s.core?.running===true,pid:nonnegative(s.core?.pid),
        memory_total:nonnegative(s.memory?.total),memory_available:nonnegative(s.memory?.available),
        rss:nonnegative(s.core?.rss),interface_up:s.interface?.up===true,
        interception_active:s.interception?.active===true,
        proxy_ok:s.health?.proxy_ok ?? null,health_checked:nonnegative(s.health?.checked),
        proxy_delay:nonnegative(s.health?.delay),diagnostics_checked:nonnegative(s.diagnostics_checked),
        errors:nonnegative(s.diagnostics_summary?.errors),pending:nonnegative(s.diagnostics_summary?.pending)});
    if(op=='locations') {
        let c=cursor();c.load('xray_core');let cfg=c.get_all('xray_core') || {};
        // snapshot.name may fall back to the server endpoint: never expose it.
        reply({mode:s.mode=='auto'?'auto':'manual',nodes:map(nodes,(n,i)=>({
            id:n.id,name:type(cfg[n.id]?.alias)=='string' && length(cfg[n.id].alias)?substr(cfg[n.id].alias,0,120):'Location '+(i+1),
            selected:n.selected===true,alive:n.alive ?? null,rtt_ms:n.rtt_ms ?? null}))});
    }
    if(target!='auto' && !length(filter(nodes,n=>n.id==target)))fail('unknown_location');
    if(s.enabled!==true || s.core?.running!==true)fail('proxy_not_running');
    if(s.operation_busy===true || index(['pending','running'],s.job?.state)>=0)fail('busy');
    let d=invoke(['launch','select',target]);
    if(d.action!='select' || index(['pending','running','done'],d.state)<0 || !d.id)fail('operation_rejected');
    reply({accepted:true,target,job:job(d)});
} catch(e) { fail('internal_error'); }
