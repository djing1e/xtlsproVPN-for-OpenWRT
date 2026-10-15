// URLTest configuration and selection policy. All state changes use Xray's API;
// existing streams keep their outbound and the core is never restarted here.
function fail(message) { die('URLTest: ' + message); }
function clone(value) { return json(sprintf('%J', value)); }
function integer(value, fallback, min, max) {
    if (value == null) return fallback;
    if (!match('' + value, /^[0-9]+$/)) fail('invalid numeric setting');
    let n = int(value);
    if (n < min || n > max) fail('numeric setting out of range');
    return n;
}
function options(raw) {
    raw = raw || {};
    for (let key, value in raw)
        if (key != 'interval_seconds' && key != 'tolerance_ms' && key != 'idle_seconds' &&
            key != 'testing_url') fail('unsupported setting ' + key);
    let url = raw.testing_url || 'https://cp.cloudflare.com/generate_204';
    if (!match(url, /^https:\/\/[^[:space:]]+$/)) fail('test URL must use HTTPS');
    return { interval_seconds: integer(raw.interval_seconds, 60, 10, 86400),
        tolerance_ms: integer(raw.tolerance_ms, 50, 0, 60000),
        idle_seconds: integer(raw.idle_seconds, 600, 10, 86400), testing_url: url };
}
function attach(config, nodes, selected, raw_options) {
    let opts = options(raw_options);
    if (type(nodes) != 'array' || !length(nodes) || length(nodes) > 32)
        fail('expected 1..32 test candidates');
    let peers = [], tags = {}, initial = null, bootstrap = [];
    for (let node in nodes) {
        if (!match(node.id || '', /^[a-f0-9]{64}$/) || tags[node.id]) fail('invalid or duplicate node ID');
        tags[node.id] = true;
        let tag = 'node-' + node.id;
        if (node.id == selected) initial = tag;
        let outbound = clone(node.outbound);
        let host = outbound.settings?.vnext?.[0]?.address;
        if (!host || outbound.protocol != 'vless') fail('expected VLESS candidate');
        push(bootstrap, 'full:' + host);
        outbound.tag = tag;
        outbound.streamSettings = outbound.streamSettings || {};
        outbound.streamSettings.sockopt = { domainStrategy: 'UseIPv4v6' };
        push(config.outbounds, outbound);
        let port = 11000 + length(peers), inbound = 'probe-' + node.id;
        push(config.inbounds, { tag: inbound, listen: '127.0.0.1', port, protocol: 'socks',
            settings: { auth: 'noauth', udp: false } });
        push(peers, { id: node.id, tag, port, inbound });
    }
    if (!initial) fail('selected node is not in candidates');
    config.dns.servers[0].domains = bootstrap;
    // Xray's loopback outbound does not increment outbound socket counters.
    // A local SOCKS hop supplies real group-only accounting for the idle timer;
    // probes bypass it. Both listeners remain loopback-only.
    push(config.outbounds, { tag: 'urltest-entry', protocol: 'socks',
        settings: { servers: [{address:'127.0.0.1',port:10822}] } });
    push(config.inbounds, {tag:'urltest-dispatch',listen:'127.0.0.1',port:10822,protocol:'socks',
        settings:{auth:'noauth',udp:true}});
    let before = [
        { type: 'field', inboundTag: ['urltest-api-in'], outboundTag: 'urltest-api' },
        { type: 'field', inboundTag: ['urltest-dispatch'], balancerTag: 'urltest-main' }
    ];
    for (let peer in peers)
        push(before, { type: 'field', inboundTag: [peer.inbound], outboundTag: peer.tag });
    for (let rule in config.routing.rules) {
        if (rule.outboundTag == 'proxy') rule.outboundTag = 'urltest-entry';
        push(before, rule);
    }
    config.routing.rules = before;
    // A single initial selector gives deterministic startup; OverrideBalancerTarget
    // may then select any validated node tag without touching live connections.
    config.routing.balancers = [{ tag: 'urltest-main', selector: [initial], strategy: { type: 'roundRobin' } }];
    config.api = { tag: 'urltest-api', services: ['RoutingService', 'StatsService', 'HandlerService'] };
    push(config.inbounds, { tag: 'urltest-api-in', listen: '127.0.0.1', port: 10820,
        protocol: 'dokodemo-door', settings: { address: '127.0.0.1' } });
    config.stats = {};
    config.policy = { system: { statsOutboundUplink: true, statsOutboundDownlink: true } };
    return { version: 1, api: '127.0.0.1:10820', balancer: 'urltest-main', initial,
        peers, options: opts, counter_prefix: 'outbound>>>urltest-entry>>>traffic>>>' };
}
function choose(current, samples, tolerance) {
    let best = null, current_ms = null;
    for (let sample in samples) {
        if (sample.ms == null || type(sample.ms) != 'int' || sample.ms < 0) continue;
        if (sample.tag == current) current_ms = sample.ms;
        if (best == null || sample.ms < best.ms) best = sample;
    }
    // No healthy node: retain selection, never fall back silently to direct.
    if (best == null) return current;
    if (current_ms == null) return best.tag;
    return current_ms - best.ms > tolerance ? best.tag : current;
}
function due(state, now, traffic, opts) {
    let next = clone(state || {});
    if (now < (next.last_activity || 0) || now < (next.last_check || 0)) {
        next.last_activity = now; delete next.last_check;
    }
    if (next.last_activity == null || traffic != next.traffic) next.last_activity = now;
    next.traffic = traffic;
    // A fresh process always gets one initial test; afterward idle groups sleep.
    let idle = next.last_check != null && now - next.last_activity >= opts.idle_seconds;
    return { state: next, run: !idle && (next.last_check == null || now - next.last_check >= opts.interval_seconds), idle };
}
return { options, attach, choose, due };
