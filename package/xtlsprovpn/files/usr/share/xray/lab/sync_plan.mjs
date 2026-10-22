"use strict";
function canonical(v) {
    if(type(v)=='object')return ['object',map(sort(keys(v)),k=>[k,canonical(v[k])])];
    if(type(v)=='array')return ['array',map(v,canonical)];
    return [type(v),v];
}
function same(a,b) {return sprintf('%J',canonical(a))==sprintf('%J',canonical(b));}
function dns_tag(t) {return t=='dns_conf_inbound' || t=='dns_server_inbound:5300' || index(t || '', 'fx_dns_')==0;}
function dependency_ok(v,tags) {
    if(type(v)=='array')return !length(filter(v,x=>!dependency_ok(x,tags)));
    if(type(v)!='object')return true;
    if(v.dialerProxy && index(tags,v.dialerProxy)<0)return false;
    if(v.proxySettings?.tag && index(tags,v.proxySettings.tag)<0)return false;
    return !length(filter(values(v),x=>!dependency_ok(x,tags)));
}
function probe(candidate,node,port) {
    const dns=filter(candidate.inbounds || [],x=>x.tag=='dns_server_inbound:5300');
    if(length(dns)!=1)return null;
    let rules=[];
    for(let original in candidate.routing?.rules || []) {
        const tags=filter(original.inboundTag || [],dns_tag);
        if(!length(tags))continue;
        let r={...original,inboundTag:tags};
        if(r.balancerTag) {
            if(r.balancerTag!='fx_main')return null;
            delete r.balancerTag;r.outboundTag=node.tag;
        }
        push(rules,r);
    }
    const safety='fx_sync_probe';
    let outbounds=filter(candidate.outbounds || [],o=>
        index(['direct','dynamic_direct','dns_server_outbound'],o.tag)>=0 || index(o.tag || '', 'fx_dns_')==0);
    outbounds=[{tag:'blackhole_outbound',protocol:'blackhole'},...outbounds,node];
    const tags=map(outbounds,o=>o.tag);
    if(length(filter(rules,r=>r.outboundTag && index(tags,r.outboundTag)<0)) ||
        !dependency_ok(outbounds,tags))return null;
    let c={log:{loglevel:'warning',access:'none'},
        inbounds:[{tag:safety,listen:'127.0.0.1',port,protocol:'socks',settings:{auth:'noauth',udp:false}},
                  {...dns[0],listen:'127.0.0.1',port:11981}],
        outbounds,routing:{domainStrategy:'AsIs',rules:[
            {type:'field',inboundTag:[safety],outboundTag:node.tag},...rules]},dns:candidate.dns};
    // Unknown dependencies and DNS geodata retain the original full preflight.
    // Never lower the memory guard for a probe that can still load geo databases.
    if(match(sprintf('%J',c),/(ext:|geoip:|geosite:)/))return null;
    return json(sprintf('%J',c));
}
export function sync_plan(candidate,live,metrics,now) {
    const nodes=filter(candidate?.outbounds || [],o=>index(o.tag || '', 'fx_node:')==0 && index(o.tag,'@')<0);
    const balancer=filter(candidate?.routing?.balancers || [],b=>b.tag=='fx_main')[0];
    if(!length(nodes) || !balancer || !candidate.dns)return null;
    const pool=filter(nodes,o=>length(filter(balancer.selector || [],s=>index(o.tag,s)==0))>0);
    if(!length(pool))return null;
    function latency(o) {
        let m=metrics?.observatory?.[o.tag],stamp=int(m?.last_try_time || m?.lastTryTime || 0);
        return m?.alive===true && stamp>0 && now>=stamp && now-stamp<=180 ? int(m.delay):2147483647;
    }
    const automatic=balancer.strategy?.type=='leastPing';
    const activation=automatic?sort([...pool],(a,b)=>latency(a)-latency(b)): [pool[0]];
    const changed=filter(nodes,o=>!same(o,filter(live?.outbounds || [],x=>x.tag==o.tag)[0]));
    let steps=[];
    for(let node in changed) {
        const c=probe(candidate,node,12000);
        if(!c)return null;
        push(steps,{config:c,port:12000,dns:false,node:node.tag});
    }
    // An unavailable newly added node must not veto every other usable path.
    // In manual mode only the explicitly selected node may activate the update.
    for(let node in activation) {
        const c=probe(candidate,node,11980);
        if(!c)return null;
        push(steps,{config:c,port:11980,dns:true,alternative:automatic,node:node.tag});
    }
    return {mode:'sequential',minimum_kb:32768,gomemlimit:'24MiB',changed:length(changed),steps};
};
