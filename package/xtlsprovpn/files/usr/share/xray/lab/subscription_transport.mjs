"use strict";
// Subscription traffic must use a per-node listener: generic SOCKS can route
// the subscription host DIRECT according to the user domain/IP policy.
export function subscription_proxy(state,runtime) {
    if (!state?.core?.running) return '';
    let nodes=sort(filter(state.nodes || [],n=>n.alive===true),
        (a,b)=>a.selected!=b.selected?(a.selected?-1:1):(a.rtt_ms || 0)-(b.rtt_ms || 0));
    for (let n in nodes) {
        const tag='fx_probe:'+n.id,out='fx_node:'+n.id;
        const inbound=filter(runtime?.inbounds || [],x=>x.tag==tag)[0];
        const routes=filter(runtime?.routing?.rules || [],r=>
            length(r.inboundTag || [])==1 && r.inboundTag[0]==tag && r.outboundTag==out);
        if (inbound?.listen=='127.0.0.1' && inbound.protocol=='socks' &&
            inbound.settings?.auth=='noauth' && inbound.settings?.udp===false &&
            type(inbound.port)=='int' && inbound.port>=1024 && inbound.port<=65535 &&
            length(routes)==1 && length(filter(runtime.outbounds || [],o=>o.tag==out && o.protocol=='vless'))==1)
            return '127.0.0.1:'+inbound.port;
    }
    return '';
};
