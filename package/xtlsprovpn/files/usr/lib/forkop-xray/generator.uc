function generate(node, port, fallback_policy) {
    port = int(port || 10808);
    if (port < 1024 || port > 65535) die('SOCKS port must be 1024..65535');
    let config = {
        log: { loglevel: 'warning' },
        inbounds: [{ tag: 'local-socks', listen: '127.0.0.1', port, protocol: 'socks',
            settings: { auth: 'noauth', udp: true } }],
        outbounds: [node.outbound],
        routing: { domainStrategy: 'AsIs', rules: [] }
    };
    let policy = node.policy || fallback_policy;
    return policy ? require('native_policy').apply(config, node, policy) : config;
}
return { generate };
