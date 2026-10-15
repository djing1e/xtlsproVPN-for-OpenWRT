// Declarative LAN plan. This module never changes routes, firewall or DHCP.
function fail() { die('Routing: invalid transparent LAN scope'); }
function attach(config, scope) {
    if (type(scope) != 'object') fail();
    for (let k in keys(scope)) if (index(['interface','client_mac'], k) < 0) fail();
    let iface = scope.interface, mac = lc(scope.client_mac || '');
    if (type(iface) != 'string' || !match(iface, /^[A-Za-z0-9_.-]{1,15}$/)) fail();
    if (!match(mac, /^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/)) fail();
    // MAC scope includes the same client's IPv4 and IPv6 without guessing its IPv6 address.
    push(config.inbounds, {
        tag: 'routing-tproxy', listen: '::', port: 12345, protocol: 'dokodemo-door',
        settings: { network: 'tcp,udp', followRedirect: true },
        streamSettings: { sockopt: { tproxy: 'tproxy' } },
        sniffing: { enabled: true, routeOnly: true, destOverride: ['fakedns','http','tls','quic'] }
    });
    push(config.inbounds, {
        tag: 'routing-dns-transparent', listen: '::', port: 10554, protocol: 'dokodemo-door',
        settings: { address: '127.0.0.1', port: 53, network: 'tcp,udp', followRedirect: true },
        streamSettings: { sockopt: { tproxy: 'tproxy' } }
    });
    // Domain policy is shared with SOCKS. Only client DNS dispatch needs a new inbound tag.
    for (let rule in config.routing.rules)
        if (index(rule.inboundTag || [], 'routing-dns') >= 0)
            push(rule.inboundTag, 'routing-dns-transparent');
    let nft = 'table inet forkop_xray {\n chain ingress {\n' +
        '  type filter hook prerouting priority mangle; policy accept;\n' +
        '  iifname != "' + iface + '" return\n' +
        '  ether saddr != ' + mac + ' return\n' +
        '  meta l4proto { tcp, udp } th dport 53 counter meta mark set meta mark | 0x08000000 tproxy to :10554 accept\n' +
        '  fib daddr type local return\n' +
        '  ip daddr 198.18.0.0/15 meta l4proto { tcp, udp } counter meta mark set meta mark | 0x08000000 tproxy to :12345 accept\n' +
        '  ip6 daddr fc00::/18 meta l4proto { tcp, udp } counter meta mark set meta mark | 0x08000000 tproxy to :12345 accept\n' +
        '  ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } return\n' +
        '  ip6 daddr { ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8 } return\n' +
        '  meta l4proto { tcp, udp } counter meta mark set meta mark | 0x08000000 tproxy to :12345 accept\n' +
        ' }\n}\n';
    return { version: 1, interface: iface, client_mac: mac, table: 'forkop_xray',
        route_table: 51880, rule_priority: 104, mark: '0x08000000', nft,
        families: ['-4','-6'], applied: false };
}
return { attach };
