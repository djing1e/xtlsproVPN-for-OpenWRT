"use strict";
import { server_outbound } from './outbound.mjs';
import { roscom_features } from './roscomvpn.mjs';

// One native outbound per subscription node, shared by TCP, UDP and DNS.
// The old native generator remains the transport/firewall implementation.
export function lab_features(i, config) {
    const g = config.general || {};
    if (g.fx_dashboard != '1') return i;
    const nodes = sort(filter(keys(config), k => config[k]['.type'] == 'servers'));
    if (!length(nodes)) die('No subscription nodes for the dashboard');
    const mode = g.fx_mode == 'auto' ? 'auto' : 'manual';
    const location = g.fx_location || g.tcp_balancer_v4?.[0];
    if (mode == 'manual' && index(nodes, location) < 0) die('Selected location is absent');
    const probe = g.fx_probe_url || 'https://cp.cloudflare.com/generate_204';
    if (!match(probe, /^https:\/\/[^[:space:]]+$/)) die('Probe URL must use HTTPS');
    const interval = max(30, min(3600, int(g.fx_probe_interval || 60)));
    i.outbounds = filter(i.outbounds, o => !match(o.tag || '', /^(tcp|udp)_balancer_v4@balancer_outbound:/));
    for (let n, key in nodes) {
        push(i.outbounds, ...server_outbound(config[key], 'fx_node:' + key, config));
        push(i.inbounds, {tag:'fx_probe:' + key, listen:'127.0.0.1', port:11500+n,
            protocol:'socks', settings:{auth:'noauth',udp:false}});
        splice(i.routing.rules,0,0,{type:'field',inboundTag:['fx_probe:'+key],outboundTag:'fx_node:'+key});
    }
    i.dns.servers[0].domains = uniq(map(filter(i.outbounds,o=>index(o.tag || '', 'fx_node:')==0),
        o=>'full:'+o.settings.vnext[0].address));
    for (let rule in i.routing.rules)
        if (index(['tcp_outbound_v4','udp_outbound_v4'], rule.balancerTag) >= 0) rule.balancerTag = 'fx_main';
    i.routing.balancers = filter(i.routing.balancers, b => index(['tcp_outbound_v4','udp_outbound_v4'],b.tag) < 0);
    push(i.routing.balancers,{tag:'fx_main',selector:map(mode=='auto'?nodes:[location],k=>'fx_node:'+k),
        strategy:{type:mode=='auto'?'leastPing':'random'},fallbackTag:'blackhole_outbound'});
    // API overrides can always switch back to the full auto pool, including
    // after a boot in manual mode. Existing links keep their outbound handler.
    push(i.outbounds,{tag:'fx_auto',protocol:'loopback',settings:{inboundTag:'fx_auto_dispatch'}});
    push(i.routing.balancers,{tag:'fx_auto_pool',selector:map(nodes,k=>'fx_node:'+k),
        strategy:{type:'leastPing'},fallbackTag:'blackhole_outbound'});
    splice(i.routing.rules,0,0,{type:'field',inboundTag:['fx_auto_dispatch'],balancerTag:'fx_auto_pool'});
    i.observatory = {subjectSelector:['fx_node:'],probeUrl:probe,probeInterval:interval+'s',enableConcurrency:true};
    // No metrics/pprof or API endpoint is exposed to the LAN.
    i.metrics = {listen:'127.0.0.1:18889'};
    i.api = {tag:'api',services:['StatsService','RoutingService']};
    i.inbounds = filter(i.inbounds,x=>x.tag!='api' && x.tag!='metrics');
    push(i.inbounds,{tag:'api',listen:'127.0.0.1',port:8080,protocol:'dokodemo-door',settings:{address:'127.0.0.1'}});
    splice(i.routing.rules,0,0,{type:'field',inboundTag:['api'],outboundTag:'api'});
    i.stats = {};
    i.policy.system = {statsInboundUplink:true,statsInboundDownlink:true,statsOutboundUplink:true,statsOutboundDownlink:true};
    i.log={loglevel:g.loglevel || 'warning',access:g.fx_access_log=='1'?'/var/log/xray-lab-access.log':'none',error:'/var/log/xray-lab-error.log'};
    return roscom_features(i, config);
};
