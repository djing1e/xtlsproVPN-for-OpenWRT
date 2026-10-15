"use strict";
import { readfile } from 'fs';

// A Happ routing profile is data, never an executable configuration hook.
export function roscom_profile(p) {
    if (type(p) != 'object' || p.GlobalProxy != 'true' || p.RouteOrder != 'block-proxy-direct' ||
        p.DomainStrategy != 'IPIfNonMatch' || p.FakeDNS != 'false') die('Unsupported RoscomVPN profile semantics');
    for (let key in ['DirectSites','DirectIp','ProxySites','ProxyIp','BlockSites','BlockIp']) {
        if (type(p[key]) != 'array' || length(p[key]) > 128) die('Invalid RoscomVPN category array: '+key);
        for (let v in p[key]) if (type(v) != 'string' || !match(v, /^(geosite|geoip):[a-z0-9_-]+$/))
            die('Unsupported RoscomVPN matcher: '+key);
    }
    if (!match(p.Geoipurl || '', /^https:\/\/cdn\.jsdelivr\.net\/gh\/hydraponique\/roscomvpn-geoip@[0-9]{12}\/release\/geoip\.dat$/) ||
        !match(p.Geositeurl || '', /^https:\/\/cdn\.jsdelivr\.net\/gh\/hydraponique\/roscomvpn-geosite@[0-9]{12}\/release\/geosite\.dat$/))
        die('RoscomVPN requires a versioned official asset URL');
    if (p.RemoteDNSDomain != 'https://8.8.8.8/dns-query' || p.DomesticDNSDomain != 'https://77.88.8.8/dns-query')
        die('Unsupported RoscomVPN DNS endpoints');
    if (type(p.DnsHosts) != 'object') die('Invalid RoscomVPN DNS hosts');
    for (let domain, ip in p.DnsHosts)
        if (!match(domain, /^[a-z0-9.-]+$/) || !iptoarr(ip)) die('Invalid RoscomVPN static host');
    return p;
};

export function roscom_features(i, config) {
    if (config.general?.fx_routing != 'roscomvpn') return i;
    const p = roscom_profile(json(readfile(getenv('FX_ROSCOM_PROFILE') || '/usr/share/xray/roscomvpn/profile.json') || 'null'));
    const site = v => replace(v, 'geosite:', 'ext:roscom-geosite.dat:');
    const ip = v => replace(v, 'geoip:', 'ext:roscom-geoip.dat:');
    const clients = ['socks_inbound','tproxy_tcp_inbound_v4','tproxy_udp_inbound_v4'];
    const endpoints = uniq(map(filter(i.outbounds, o=>index(o.tag || '', 'fx_node:')==0), o=>'full:'+o.settings.vnext[0].address));
    // Independent node probes and API always precede user policy.
    let rules = filter(i.routing.rules, r=>length(r.inboundTag || [])==1 &&
        (r.inboundTag[0]=='api' || index(r.inboundTag[0],'fx_probe:')==0));
    const add = r => push(rules, {type:'field',...r});
    add({inboundTag:['dns_conf_inbound'],ip:['1.1.1.1','77.88.8.8'],outboundTag:'direct'});
    add({inboundTag:['dns_conf_inbound'],balancerTag:'fx_main'});
    add({inboundTag:map(filter(i.inbounds,x=>index(x.tag || '', 'dns_server_inbound:')==0),x=>x.tag),outboundTag:'dns_server_outbound'});
    // Bootstrap and LAN management are router exceptions, not remote private access.
    add({inboundTag:clients,domain:endpoints,outboundTag:'direct'});
    add({inboundTag:clients,ip:['10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/4','240.0.0.0/4'],outboundTag:'direct'});
    for (let category in ['Block','Proxy','Direct']) {
        const target = category=='Proxy'?{balancerTag:'fx_main'}:{outboundTag:category=='Block'?'blackhole_outbound':'direct'};
        if (length(p[category+'Sites'])) add({inboundTag:clients,domain:map(p[category+'Sites'],site),...target});
        if (length(p[category+'Ip'])) add({inboundTag:clients,ip:map(p[category+'Ip'],ip),...target});
    }
    add({inboundTag:clients,balancerTag:'fx_main'});
    i.routing.rules=rules;
    i.routing.domainStrategy='IPIfNonMatch';
    delete i.fakedns;
    // Resolver order repeats the profile's proxy-before-direct precedence.
    i.dns={tag:'dns_conf_inbound',queryStrategy:'UseIPv4',disableFallbackIfMatch:true,
        hosts:p.DnsHosts,servers:[
            {address:'1.1.1.1',port:53,domains:endpoints,skipFallback:true},
            {address:p.RemoteDNSDomain,domains:map(p.ProxySites,site),skipFallback:true},
            {address:p.DomesticDNSDomain,domains:map(p.DirectSites,site),skipFallback:true},
            {address:p.RemoteDNSDomain}
        ]};
    return i;
};
