let fs = require('fs');
import { cursor } from 'uci';
let uci = cursor(ARGV[0]);
let fixture = getenv('XRAY_LAB_NETWORK_JSON');
let lan;
if (fixture) lan = json(fs.readfile(fixture));
else {
    let proc = fs.popen('ubus call network.interface.lan status', 'r');
    if (!proc) die('Cannot read LAN status');
    let body = proc.read('all');
    if (proc.close() != 0) die('Cannot read LAN status');
    lan = json(body);
}
let iface = lan?.l3_device, addr = lan?.['ipv4-address']?.[0];
if (!lan?.up || !match(iface || '', /^[A-Za-z0-9_.-]{1,15}$/) ||
    !match(addr?.address || '', /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/))
    die('LAN must be up with an IPv4 address');
let cached = json(fs.readfile(getenv('FX_SUBSCRIPTION_CACHE') || '/etc/forkop-xray/subscription.json'));
let nodes = cached.nodes || [];
if (!length(nodes)) die('No cached subscription nodes');
let previous = {};
try { let old = cursor(); old.load('xray_core'); previous = old.get_all('xray_core') || {}; } catch (e) {}
let catalog = {}, byid = {}, names = {}, selected;
for (let node in nodes) {
    let v = node.outbound?.settings?.vnext?.[0];
    if (node.outbound?.protocol != 'vless' || !v?.address || !v?.users?.[0]?.id ||
        !match(node.id || '', /^[0-9a-f]{64}$/)) die('Invalid cached VLESS node');
    let key;
    for (let offset = 0; offset <= 58; offset++) {
        let candidate = 'cfg' + substr(node.id, offset, 6);
        if (!catalog[candidate]) { key = candidate; break; }
    }
    if (!key) die('Cannot allocate unique native server identifier');
    catalog[key] = node; byid[node.id] = key;
    if (node.name && !names[node.name]) names[node.name] = key;
    if (node.id == cached.selected) selected = key;
}
if (!selected) selected = keys(catalog)[0];
function selection(field) {
    let old = previous.general?.[field];
    if (old == null) return [selected];
    if (type(old) != 'array') old = [old];
    let result = [], seen = {};
    for (let key in old) {
        let oldserver = previous[key];
        let next = byid[oldserver?.subscription_id] || names[oldserver?.alias];
        // Upgrade the earlier single-node deployment using the current selected node.
        if (!next && key == 'labnode01') next = selected;
        if (next && !seen[next]) { push(result,next); seen[next] = true; }
    }
    return length(old) && !length(result) ? [selected] : result;
}
uci.set('xray_core', 'general', 'general');
let opts = {
    transparent_proxy_enable:'0', xray_bin:'/usr/libexec/forkop-xray/xray',
    tproxy_sniffing:'1', route_only:'1', general_balancer_strategy:'random',
    tcp_balancer_v4:selection('tcp_balancer_v4'), udp_balancer_v4:selection('udp_balancer_v4'),
    lab_iface:iface, lab_address:addr.address, lab_mask:''+addr.mask,
    tproxy_ifaces_v4:[iface], tproxy_ifaces_v6:[], bypassed_domain_rules:[],
    forwarded_domain_rules:[], blocked_domain_rules:[],
    geoip_direct_code_list:[], geoip_direct_code_list_v6:[],
    fast_dns:'1.1.1.1:53', secure_dns:'1.1.1.1:53', default_dns:'1.1.1.1:53',
    fast_dns_method:'udp', secure_dns_method:'udp', fw4_counter:'1',
    access_log:'1', loglevel:'warning', dnsmasq_integration_mode:'global',
    dynamic_direct_tcp4:'0', dynamic_direct_tcp6:'0', dynamic_direct_udp4:'0', dynamic_direct_udp6:'0'
};
opts.custom_configuration_hook = `return function(i) {
    let tags = ['tproxy_tcp_inbound_v4','tproxy_udp_inbound_v4','socks_inbound'];
    i.inbounds = filter(i.inbounds, x => index(tags,x.tag)>=0 || index(x.tag,'dns_server_inbound:')==0);
    for (let x in i.inbounds) {
        if (x.tag == 'socks_inbound' || index(x.tag,'dns_server_inbound:')==0) x.listen='127.0.0.1';
        x.port=int(x.port);
    }
    splice(i.routing.rules,0,0,
        {inboundTag:['dns_conf_inbound'],ip:['1.1.1.1'],outboundTag:'direct'},
        {inboundTag:['dns_conf_inbound'],balancerTag:'udp_outbound_v4'},
        {inboundTag:tags,ip:['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/4','240.0.0.0/4'],outboundTag:'direct'},
        {inboundTag:tags,network:'tcp',balancerTag:'tcp_outbound_v4'},
        {inboundTag:tags,network:'udp',balancerTag:'udp_outbound_v4'});
    let domains = [];
    for (let o in i.outbounds) if (o.protocol=='vless') {
        let name='full:'+o.settings.vnext[0].address;
        if (index(domains,name)<0) push(domains,name);
    }
    i.dns.servers=[{address:'1.1.1.1',port:53,domains,skipFallback:true},{address:'9.9.9.9',port:53}];
    i.dns.queryStrategy='UseIPv4';
    i.dns.disableFallbackIfMatch=true;
    i.log={loglevel:'warning',access:'/var/log/xray-lab-access.log',error:'/var/log/xray-lab-error.log'};
    return i;
};`;
for (let key,value in opts) if (type(value)!='array' || length(value)) uci.set('xray_core','general',key,value);
if (previous.general?.fx_dashboard=='1') {
    for (let key in ['fx_dashboard','fx_mode','fx_probe_url','fx_probe_interval','fx_watchdog_enabled','fx_watch_interface','fx_watch_delay','fx_routing','fx_rule_block_domains','fx_rule_block_ips','fx_rule_proxy_domains','fx_rule_proxy_ips','fx_rule_direct_domains','fx_rule_direct_ips','fx_access_log','fx_start_authorized'])
        if (previous.general[key]!=null) uci.set('xray_core','general',key,previous.general[key]);
    let old = previous[previous.general.fx_location];
    let location=byid[old?.subscription_id] || names[old?.alias] || selected;
    uci.set('xray_core','general','fx_location',location);
    let group=previous.general.fx_mode=='auto'?keys(catalog):[location];
    uci.set('xray_core','general','tcp_balancer_v4',group);
    uci.set('xray_core','general','udp_balancer_v4',group);
}
for (let key, node in catalog) {
    let outbound = node.outbound, vnext = outbound.settings.vnext[0];
    uci.set('xray_core',key,'servers');
    for (let option,value in {alias:node.name || vnext.address, subscription_id:node.id,
        protocol:'vless',server:vnext.address,server_port:''+vnext.port,
        password:vnext.users[0].id,vless_tls:outbound.streamSettings?.security || 'none',transport:'tcp',tcp_guise:'none',
        vless_flow_reality:vnext.users[0].flow || 'none',
        vless_reality_server_name:outbound.streamSettings?.realitySettings?.serverName || '',
        vless_reality_fingerprint:outbound.streamSettings?.realitySettings?.fingerprint || 'firefox',
        vless_reality_public_key:outbound.streamSettings?.realitySettings?.publicKey || outbound.streamSettings?.realitySettings?.password || '',
        vless_reality_short_id:outbound.streamSettings?.realitySettings?.shortId || '',
        vless_reality_spider_x:outbound.streamSettings?.realitySettings?.spiderX || '/',
        vless_encryption:vnext.users[0].encryption || 'none', custom_config:sprintf('%J',outbound)})
        uci.set('xray_core',key,option,value);
}
if (!uci.commit('xray_core')) die('Cannot save private lab UCI config');
fs.chmod(ARGV[0]+'/xray_core',0600);
printf('Imported %d subscription nodes; LAN %s; gateway/DNS %s/%d.\n',length(nodes),iface,addr.address,addr.mask);
