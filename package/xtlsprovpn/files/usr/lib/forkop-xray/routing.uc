// Development compiler: normalized Forkop rules -> Xray. No firewall/UCI writes.
// Unknown matchers are errors: silently dropping one would widen a route.
let fields = ['domain', 'domain_suffix', 'domain_keyword', 'domain_regex',
    'ip_cidr', 'source_ip_cidr', 'port', 'port_range', 'network'];
function fail(s) { die('Routing: ' + s); }
function values(obj, key) {
    let v = obj[key];
    if (v == null) return [];
    if (type(v) != 'array') fail(key + ' must be an array');
    return v;
}
function domains(rule) {
    let result = [];
    for (let key in ['domain', 'domain_suffix', 'domain_keyword', 'domain_regex']) {
        let prefix = key == 'domain' ? 'full:' : key == 'domain_suffix' ? 'domain:' :
            key == 'domain_keyword' ? 'keyword:' : 'regexp:';
        for (let value in values(rule, key)) {
            if (type(value) != 'string' || value == '') fail('empty or invalid domain matcher');
            push(result, prefix + value);
        }
    }
    return result;
}
function port_value(v, range) {
    let s = '' + v;
    if (range) s = replace(s, /:/g, '-');
    let m = match(s, /^([0-9]+)(-([0-9]+))?$/);
    if (!m) fail('invalid port');
    let low = int(m[1]), high = m[3] == null ? low : int(m[3]);
    if (low < 1 || high > 65535 || low > high) fail('invalid port range');
    return low == high ? '' + low : low + '-' + high;
}
function copy(obj) { return json(sprintf('%J', obj)); }
function validate_keys(rule) {
    if (type(rule) != 'object') fail('rule must be an object');
    for (let key, value in rule) {
        let known = false;
        for (let allowed in fields) if (allowed == key) known = true;
        if (!known) fail('unsupported matcher ' + key);
    }
}
function compile_rule(rule, target, inbound) {
    validate_keys(rule);
    let base = { type: 'field', inboundTag: inbound, outboundTag: target };
    let sources = values(rule, 'source_ip_cidr');
    if (length(sources)) base.source = sources;
    let ports = [];
    for (let p in values(rule, 'port')) push(ports, port_value(p, false));
    for (let p in values(rule, 'port_range')) push(ports, port_value(p, true));
    if (length(ports)) base.port = join(',', ports);
    let networks = values(rule, 'network');
    for (let n in networks) if (n != 'tcp' && n != 'udp') fail('invalid network');
    if (length(networks)) base.network = join(',', networks);
    let d = domains(rule), ips = values(rule, 'ip_cidr'), result = [];
    // sing-box groups destination-domain and destination-IP matchers with OR.
    // Xray combines distinct fields with AND, so emit adjacent rules.
    if (length(d)) { let r = copy(base); r.domain = d; push(result, r); }
    if (length(ips)) { let r = copy(base); r.ip = ips; push(result, r); }
    if (!length(d) && !length(ips)) {
        if (!length(ports) && !length(networks) && !length(sources))
            fail('empty rule would capture every destination');
        push(result, base);
    }
    return result;
}
function compile(profile, node, socks_port, nodes) {
    if (profile?.version != 1) fail('expected normalized profile version 1');
    for (let key, value in profile)
        if (key != 'version' && key != 'sections' && key != 'settings' && key != 'urltest' && key != 'lan') fail('unsupported profile field ' + key);
    if (type(profile.sections) != 'array' || !length(profile.sections)) fail('no sections');
    let settings = profile.settings || {};
    // Settings outside this implemented subset must not appear to be supported.
    for (let key, value in settings)
        if (key != 'dns_server' && key != 'bootstrap_dns_server' && key != 'dns_rewrite_ttl' &&
            key != 'disable_quic') fail('unsupported setting ' + key);
    let dns_address = settings.dns_server || 'https://1.1.1.1/dns-query';
    if (!match(dns_address, /^https:\/\/[0-9.]+\/dns-query$/))
        fail('this stage requires DoH with a literal IPv4 address');
    let bootstrap = settings.bootstrap_dns_server || '77.88.8.8';
    if (!match(bootstrap, /^[0-9.]+$/)) fail('invalid bootstrap resolver');
    let proxy = copy(node.outbound); proxy.tag = 'proxy';
    proxy.streamSettings = proxy.streamSettings || {};
    proxy.streamSettings.sockopt = { domainStrategy: 'UseIPv4v6' };
    let host = proxy.settings?.vnext?.[0]?.address;
    if (!host) fail('expected VLESS node');
    let inbounds = ['routing-socks', 'routing-tproxy'];
    let rules = [{ type: 'field', inboundTag: ['routing-dns'], outboundTag: 'dns-out' },
        { type: 'field', inboundTag: ['dns-upstream'], outboundTag: 'direct' }];
    if (settings.disable_quic == true)
        push(rules, { type: 'field', inboundTag: inbounds, protocol: ['quic'], outboundTag: 'block' });
    let dns_servers = [{ address: bootstrap, domains: ['full:' + host], skipFallback: true, finalQuery: true }];
    let seen_sections = {};
    for (let section in profile.sections) {
        if (!section.name || seen_sections[section.name]) fail('missing or duplicate section name');
        seen_sections[section.name] = true;
        for (let key, value in section)
            if (key != 'name' && key != 'action' && key != 'rules') fail('unsupported section field ' + key);
        let target = section.action == 'connection' ? 'proxy' : section.action == 'bypass' ? 'direct' :
            section.action == 'block' ? 'block' : null;
        if (target == null) fail('unsupported section action');
        if (type(section.rules) != 'array' || !length(section.rules)) fail('section has no expanded rules');
        let dd = [];
        for (let rule in section.rules) {
            let d = [];
            for (let r in compile_rule(rule, target, inbounds)) {
                push(rules, r);
                // Reuse domain strings for DNS instead of constructing the large list twice.
                if (r.domain) d = r.domain;
            }
            // Source-aware FakeDNS needs separate resolvers; never widen these silently.
            if (length(d) && length(values(rule, 'source_ip_cidr')))
                fail('source-aware domain DNS is not implemented yet');
            for (let value in d) push(dd, value);
        }
        if (length(dd)) {
            // Xray DNS chooses specificity, not Forkop's first matching section.
            // Until isolated resolvers are implemented, reject multiple domain sections.
            if (length(dns_servers) > 1) fail('multiple domain sections need ordered DNS handling');
            push(dns_servers, { address: target == 'direct' ? dns_address : 'fakedns',
                domains: dd, skipFallback: true, finalQuery: true });
        }
    }
    push(dns_servers, dns_address);
    let config = {
        log: { loglevel: 'warning' },
        inbounds: [
            { tag: 'routing-socks', listen: '127.0.0.1', port: int(socks_port || 10818), protocol: 'socks',
                settings: { auth: 'noauth', udp: true },
                sniffing: { enabled: true, destOverride: ['fakedns', 'http', 'tls', 'quic'], routeOnly: true } },
            { tag: 'routing-dns', listen: '127.0.0.1', port: 10553, protocol: 'dokodemo-door',
                settings: { address: bootstrap, port: 53, network: 'tcp,udp' } }
        ],
        // First outbound is the default for unmatched traffic.
        outbounds: [
            { tag: 'direct', protocol: 'freedom', settings: { domainStrategy: 'UseIPv4v6' } },
            proxy,
            { tag: 'block', protocol: 'blackhole', settings: {} },
            { tag: 'dns-out', protocol: 'dns', settings: { rules: [
                { action: 'return', qType: 65, rCode: 5 },
                { action: 'return', domain: ['domain:use-application-dns.net'], rCode: 5 },
                { action: 'hijack', qType: '1,28' },
                { action: 'direct' }
            ] } }
        ],
        dns: { tag: 'dns-upstream', queryStrategy: 'UseIP', disableFallbackIfMatch: true, servers: dns_servers },
        fakedns: [{ ipPool: '198.18.0.0/15', poolSize: 65535 }, { ipPool: 'fc00::/18', poolSize: 65535 }],
        routing: { domainStrategy: 'AsIs', rules }
    };
    let lan = profile.lan != null ? require('transparent').attach(config, profile.lan) : null;
    let manifest = null;
    if (profile.urltest != null)
        manifest = require('urltest').attach(config, nodes, node.id, profile.urltest);
    let warnings = [
        'Development check only: LAN interception and system DNS are not installed.',
        'Xray 26.7.28 FakeDNS TTL is 1 second; Forkop TTL rewriting is not implemented.'
    ];
    if (manifest) push(warnings, 'URLTest is prepared; its periodic controller is not installed as a service yet.');
    else push(warnings, 'This profile uses a single manually selected node.');
    return { config, urltest: manifest, lan, warnings };
}
// Accept decompiled source lists; a binary SRS is deliberately not guessed as text.
// Keep each source rule intact, especially network+port+IP clauses such as Discord.
function source_rules(source) {
    if (type(source) != 'object' || (source.version != 1 && source.version != 2 && source.version != 3))
        fail('unsupported source ruleset version');
    for (let key, value in source)
        if (key != 'version' && key != 'rules') fail('unsupported source ruleset field ' + key);
    if (type(source.rules) != 'array' || !length(source.rules)) fail('empty source ruleset');
    let result = [];
    function append(rule) {
        if (rule.type == 'logical') {
            for (let key, value in rule)
                if (key != 'type' && key != 'mode' && key != 'rules') fail('unsupported logical ruleset field ' + key);
            if (rule.mode != 'or' || type(rule.rules) != 'array' || !length(rule.rules))
                fail('only nonempty logical OR lists are supported');
            for (let child in rule.rules) append(child);
            return;
        }
        let normalized = copy(rule);
        if (normalized.type == 'default') delete normalized.type;
        // sing-box accepts scalar or array for its Listable fields.
        for (let key in fields)
            if (normalized[key] != null && type(normalized[key]) != 'array') normalized[key] = [normalized[key]];
        compile_rule(normalized, 'validate', ['validate']);
        push(result, normalized);
    }
    for (let rule in source.rules) append(rule);
    return result;
}
return { compile, compile_rule, domains, source_rules };
