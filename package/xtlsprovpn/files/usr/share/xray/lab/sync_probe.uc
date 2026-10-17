#!/usr/bin/ucode
let fs=require('fs');
import { sync_plan } from './sync_plan.mjs';
let c=json(fs.readfile(ARGV[0]) || 'null');
let old={}; try {old=json(fs.readfile(ARGV[1]) || '{}');}catch(e){}
if (!c || type(c.outbounds)!='array')die('Missing candidate configuration');
if(ARGV[6]) {
    let metrics;try {metrics=json(fs.readfile(ARGV[5]) || 'null');}catch(e){}
    let plan=sync_plan(c,old,metrics,time());
    if(plan) {
        let lines=[];
        for(let n,step in plan.steps) {
            const path=ARGV[2]+'.'+n+'.json';
            step.config.log.error=ARGV[4];
            if(!fs.writefile(path,sprintf('%J',step.config)))die('Cannot stage sequential probe');
            if(!fs.chmod(path,0600))die('Cannot protect sequential probe');
            push(lines,''+step.port+' '+path+' '+(step.dns?'1':'0'));
        }
        if(!fs.writefile(ARGV[3],join('\n',lines)+'\n') ||
            !fs.writefile(ARGV[6],sprintf('%J',{mode:plan.mode,minimum_kb:plan.minimum_kb,gomemlimit:plan.gomemlimit,changed:plan.changed})))
            die('Cannot stage subscription probe plan');
        fs.chmod(ARGV[3],0600);fs.chmod(ARGV[6],0600);
        exit(0);
    }
    if(!fs.writefile(ARGV[6],sprintf('%J',{mode:'independent',minimum_kb:98304,gomemlimit:'64MiB'})))die('Cannot stage full probe plan');
}
let proxies=filter(c.outbounds,o=>index(o.tag || '', 'fx_node:')==0);
let socks=filter(c.inbounds || [],i=>i.tag=='socks_inbound')[0];
let dns=filter(c.inbounds || [],i=>i.tag=='dns_server_inbound:5300')[0];
if(!socks || !dns || !length(proxies))die('Missing local candidate listeners');
socks.listen='127.0.0.1';socks.port=11980;
dns.listen='127.0.0.1';dns.port=11981;
c.inbounds=[socks,dns];delete c.api;delete c.metrics;
c.routing.rules=filter(c.routing.rules || [],r=>r.outboundTag!='api' && r.outboundTag!='metrics');
function canonical(v) {
    if(type(v)=='object')return ['object',map(sort(keys(v)),k=>[k,canonical(v[k])])];
    if(type(v)=='array')return ['array',map(v,canonical)];
    return [type(v),v];
}
let ports=[];
for(let n,o in proxies) {
    let before=filter(old.outbounds || [],x=>x.tag==o.tag)[0];
    if(before && sprintf('%J',canonical(before))==sprintf('%J',canonical(o)))continue;
    let tag='fx_safety:'+n,port=12000+n;
    push(c.inbounds,{tag,listen:'127.0.0.1',port,protocol:'socks',settings:{auth:'noauth',udp:false}});
    splice(c.routing.rules,0,0,{type:'field',inboundTag:[tag],outboundTag:o.tag});
    push(ports,port);
}
c.log={loglevel:'warning',access:'none',error:ARGV[4]};
if(!fs.writefile(ARGV[2],sprintf('%J',c)) || fs.writefile(ARGV[3],join('\n',ports)+(length(ports)?'\n':''))==null)die('Cannot stage isolated probe');
fs.chmod(ARGV[2],0600);fs.chmod(ARGV[3],0600);
