"use strict";

function dns_tag(tag) {
    return tag=='dns_conf_inbound' || tag=='dns_server_inbound:5300' || index(tag || '', 'fx_dns_')==0;
}

function live_proxy(candidate,live,metrics,now) {
    const balancer=filter(candidate.routing?.balancers || [],x=>x.tag=='fx_main')[0];
    if (!balancer || !live) return null;
    let choices=[];
    for (let out in candidate.outbounds || []) {
        if (index(out.tag || '', 'fx_node:')!=0 ||
            !length(filter(balancer.selector || [],s=>index(out.tag,s)==0))) continue;
        const original=filter(live.outbounds || [],x=>x.tag==out.tag)[0];
        // A changed transport or output interface must be tested independently.
        if (sprintf('%J',out)!=sprintf('%J',original)) continue;
        const id=substr(out.tag,8), tag='fx_probe:'+id;
        const inbound=filter(live.inbounds || [],x=>x.tag==tag)[0];
        const route=filter(live.routing?.rules || [],r=>
            length(r.inboundTag || [])==1 && r.inboundTag[0]==tag && r.outboundTag==out.tag)[0];
        if (!route || inbound?.listen!='127.0.0.1' || inbound.protocol!='socks' ||
            inbound.settings?.auth!='noauth' || type(inbound.port)!='int' ||
            inbound.port<1024 || inbound.port>65535) continue;
        const observation=metrics?.observatory?.[out.tag];
        const stamp=int(observation?.last_try_time || observation?.lastTryTime || 0);
        const interval=int(match(live.observatory?.probeInterval || '60s',/^([0-9]+)s$/)?.[1] || 60);
        const healthy=observation?.alive===true && stamp>0 && now>=stamp && now-stamp<=max(180,3*interval);
        if (balancer.strategy?.type=='leastPing' && !healthy) continue;
        push(choices,{port:inbound.port,delay:healthy?int(observation.delay):0});
    }
    return sort(choices,(a,b)=>a.delay-b.delay)[0] || null;
}

// Reuse only the dedicated per-node SOCKS listener. The generic SOCKS listener
// follows domain policy and could silently send a requested proxy DNS DIRECT.
export function dns_probe(candidate,options,live,metrics,now) {
    let c=json(sprintf('%J',candidate));
    c.inbounds=filter(c.inbounds || [],x=>x.tag=='dns_server_inbound:5300');
    if(length(c.inbounds)!=1)die('DNS inbound 5300 is required');
    c.inbounds[0].listen='127.0.0.1';c.inbounds[0].port=15354;
    delete c.api;delete c.metrics;
    c.routing.rules=filter(c.routing.rules,r=>r.outboundTag!='api' && r.outboundTag!='metrics');
    let proxy=null;
    // The live probe listener has UDP disabled. UDP proxy DNS retains the full
    // independent check; TCP/DoH/DoT can use the already established transport.
    let light=options?.enabled=='1' &&
        (options.via_proxy!='1' || index(['tcp','doh','dot'],options.protocol)>=0);
    if(light && options.via_proxy=='1') {
        proxy=live_proxy(candidate,live,metrics,now);
        light=proxy!=null;
    }
    if(light) {
        let rules=[];
        for(let rule in c.routing.rules) {
            const tags=filter(rule.inboundTag || [],dns_tag);
            if(!length(tags))continue;
            let r={...rule,inboundTag:tags};
            if(r.balancerTag) {
                if(r.balancerTag!='fx_main' || !proxy) {light=false;break;}
                delete r.balancerTag;r.outboundTag='fx_dns_probe_proxy';
            }
            push(rules,r);
        }
        if(light) {
            c.routing={domainStrategy:'AsIs',rules};
            c.outbounds=filter(c.outbounds || [],o=>
                index(['direct','dynamic_direct','dns_server_outbound','blackhole_outbound'],o.tag)>=0 ||
                index(o.tag || '', 'fx_dns_')==0);
            // Unexpected/unmatched traffic must never fall back to DIRECT.
            c.outbounds=filter(c.outbounds,o=>o.tag!='blackhole_outbound');
            splice(c.outbounds,0,0,{tag:'blackhole_outbound',protocol:'blackhole'});
            if(proxy)push(c.outbounds,{tag:'fx_dns_probe_proxy',protocol:'socks',
                settings:{servers:[{address:'127.0.0.1',port:proxy.port}]},
                streamSettings:{sockopt:{mark:253}}});
            delete c.observatory;delete c.burstObservatory;delete c.policy;delete c.fakedns;delete c.stats;
        }
    }
    return {config:c,mode:light?'shared-transport':'independent',
        minimum_kb:light?32768:65536,gomemlimit:light?'24MiB':'64MiB'};
};
