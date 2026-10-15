"use strict";
import { normalize_rules, rule_keys } from '../lab/routing_options.mjs';
export function user_routing_features(i, config) {
    const input={},clients=['socks_inbound','tproxy_tcp_inbound_v4','tproxy_udp_inbound_v4'];
    for(let key in rule_keys)input[key]=config.general?.['fx_rule_'+key] || [];
    const options=normalize_rules(input);let custom=[];
    for(let action in ['block','proxy','direct']) {
        let target=action=='proxy'?{balancerTag:'fx_main'}:{outboundTag:action=='block'?'blackhole_outbound':'direct'};
        if(length(options[action+'_domains']))push(custom,{type:'field',inboundTag:clients,domain:options[action+'_domains'],...target});
        if(length(options[action+'_ips']))push(custom,{type:'field',inboundTag:clients,ip:options[action+'_ips'],...target});
    }
    if(!length(custom))return i;
    const endpoints=uniq(filter(map(filter(i.outbounds || [],o=>index(o.tag || '','fx_node:')==0),o=>o.settings?.vnext?.[0]?.address || o.settings?.servers?.[0]?.address),x=>x!=null));
    let guards=[];
    if(length(endpoints))push(guards,{type:'field',inboundTag:clients,domain:map(endpoints,x=>'full:'+x),outboundTag:'direct'});
    push(guards,{type:'field',inboundTag:clients,ip:['10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/4','240.0.0.0/4','::1/128','fc00::/7','fe80::/10'],outboundTag:'direct'});
    const quic=filter(i.routing.rules,r=>r.network=='udp' && r.port=='443' && r.outboundTag=='blackhole_outbound');
    i.routing.rules=[...quic,...guards,...custom,...i.routing.rules];
    i.routing.domainStrategy='IPIfNonMatch';return i;
};
