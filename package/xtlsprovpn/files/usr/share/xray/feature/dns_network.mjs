"use strict";
import { resolver_endpoints } from '../lab/dns_options.mjs';

export function dns_network_features(i,config) {
    const o=config.general?._fx_dns;
    if (!o) return i;
    const clients=['socks_inbound','tproxy_tcp_inbound_v4','tproxy_udp_inbound_v4'];
    if (o.output_enabled=='1') {
        for (let out in i.outbounds) if (index(out.tag || '', 'fx_node:')==0 || index(['direct','dynamic_direct'],out.tag)>=0) {
            out.streamSettings ||= {};out.streamSettings.sockopt ||= {};
            out.streamSettings.sockopt.interface=o.output_device;
        }
    }
    if (o.disable_quic=='1') {
        splice(i.routing.rules,0,0,{type:'field',inboundTag:clients,network:'udp',port:'443',outboundTag:'blackhole_outbound'});
    }
    if (o.enabled!='1') return i;
    const main=resolver_endpoints(o);
    const probe_host=match(config.general.fx_probe_url || 'https://cp.cloudflare.com/generate_204',/^https:\/\/([^\/:?#]+)/)?.[1];
    const endpoint_names=uniq([
        ...(probe_host?[probe_host]:[]),
        ...map(filter(i.outbounds,x=>index(x.tag || '', 'fx_node:')==0),x=>x.settings.vnext[0].address),
        ...map(main,e=>e.host)
    ]);
    const domains=map(filter(endpoint_names,x=>!iptoarr(x)),x=>'full:'+x);
    const strategy={ipv4:'UseIPv4',ipv6:'UseIPv6',auto:'UseIP'}[o.strategy];
    let bootstrap=map(o.bootstrap,ip=>({address:ip,port:53,domains,skipFallback:true,
        queryStrategy:'UseIPv4',tag:'fx_dns_bootstrap',timeoutMs:3000}));
    let rules=filter(i.routing.rules,r=>index(r.inboundTag || [],'dns_conf_inbound')<0);
    let generated=[{type:'field',inboundTag:['fx_dns_bootstrap'],outboundTag:'direct'}];
    let servers=[];
    for (let n,e in main) {
        let tag='fx_dns_main:'+n;
        push(servers,{address:e.address,port:e.port,tag,queryStrategy:strategy,timeoutMs:5000});
        if (o.protocol=='dot') {
            // TCP DNS framing is native; this Freedom outbound adds verified TLS.
            const tls_tag='fx_dns_tls:'+n,inner='fx_dns_tls_inner:'+n;
            push(i.outbounds,{protocol:'loopback',tag:'fx_dns_tls_dialer:'+n,settings:{inboundTag:inner}});
            push(i.outbounds,{protocol:'freedom',tag:tls_tag,settings:{},streamSettings:{
                network:'raw',security:'tls',tlsSettings:{serverName:e.host},
                sockopt:{mark:253,dialerProxy:'fx_dns_tls_dialer:'+n}
            }});
            push(generated,{type:'field',inboundTag:[tag],outboundTag:tls_tag});
            push(generated,{type:'field',inboundTag:[inner],...(o.via_proxy=='1'?{balancerTag:'fx_main'}:{outboundTag:'direct'})});
        } else {
            push(generated,{type:'field',inboundTag:[tag],...(o.via_proxy=='1'?{balancerTag:'fx_main'}:{outboundTag:'direct'})});
        }
    }
    // DNS is independent from domain policy. Bootstrap never follows the proxy.
    i.routing.rules=[...generated,...rules];
    i.dns={tag:'dns_conf_inbound',queryStrategy:strategy,disableFallbackIfMatch:true,
        hosts:i.dns.hosts || {},servers:[...bootstrap,...servers]};
    return i;
};
