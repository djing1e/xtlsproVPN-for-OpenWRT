// Router-owned listeners; native subscription DNS and ordered routing remain intact.
function fail() { die('Subscription policy is unsupported or has unresolved references'); }
function fields(value, allowed) {
    if (type(value) != 'object') fail();
    for (let key in keys(value)) if (index(allowed, key) < 0) fail();
}
function extract(c, proxy_tag) {
    let p = {};
    for (let k in ['dns','routing','policy','stats','fakedns'])
        if (c[k] != null) p[k] = c[k];
    if (!length(keys(p))) return null;
    // Features with independent listeners, file access or outbound dependencies need explicit adapters.
    for (let k in ['api','reverse','observatory','burstObservatory','transport'])
        if (c[k] != null) fail();
    if (p.routing != null) {
        fields(p.routing, ['domainStrategy','domainMatcher','rules']);
        if (type(p.routing.rules) != 'array') fail();
        for (let rule in p.routing.rules) {
            fields(rule, ['type','domain','ip','port','sourcePort','network','source','protocol','attrs','outboundTag','domainMatcher']);
            if (type(rule.outboundTag) != 'string') fail();
        }
    }
    if (p.dns != null) {
        fields(p.dns, ['hosts','servers','clientIp','queryStrategy','disableCache','disableFallback',
            'disableFallbackIfMatch','tag']);
        if (type(p.dns.servers) != 'array') fail();
        for (let server in p.dns.servers) if (type(server) != 'string')
            fields(server, ['address','port','domains','expectIPs','unexpectedIPs','skipFallback',
                'clientIp','queryStrategy','timeoutMs','disableCache','finalQuery']);
    }
    if (type(c.outbounds) != 'array' || !length(c.outbounds)) fail();
    p.outbounds = [];
    let tags = {};
    for (let o in c.outbounds || []) {
        if (type(o.tag) != 'string' || o.tag == '' || tags[o.tag]) fail();
        tags[o.tag] = true;
        if (o.protocol == 'vless') {
            if (o.tag != proxy_tag) fail();
            push(p.outbounds, { tag: o.tag, protocol: 'selected-proxy' });
        } else {
            if (index(['freedom','blackhole','dns'], o.protocol) < 0) fail();
            fields(o, ['tag','protocol','settings','streamSettings']);
            if (o.streamSettings != null) {
                if (o.protocol != 'dns') fail();
                fields(o.streamSettings, ['sockopt']);
                fields(o.streamSettings.sockopt, ['dialerProxy']);
                if (o.streamSettings.sockopt.dialerProxy != (proxy_tag || 'proxy')) fail();
            }
            if (o.settings != null) {
                if (o.protocol == 'freedom') fields(o.settings, ['domainStrategy','userLevel']);
                if (o.protocol == 'blackhole') fields(o.settings, ['response']);
                if (o.protocol == 'dns') fields(o.settings, ['network','address','port','nonIPQuery','blockTypes']);
            }
            push(p.outbounds, o);
        }
    }
    // A policy-only template refers to the conventional proxy tag.
    if (proxy_tag == null) {
        if (tags.proxy) fail();
        tags.proxy = true;
        push(p.outbounds, { tag: 'proxy', protocol: 'selected-proxy' });
    }
    if (!length(p.outbounds)) fail();
    for (let rule in p.routing?.rules || []) if (!tags[rule.outboundTag]) fail();
    for (let o in p.outbounds) if (o.protocol == 'dns' && o.settings?.nonIPQuery &&
        index(['drop','skip'], o.settings.nonIPQuery) < 0) fail();
    return json(sprintf('%J', p));
}
function apply(config, node, policy) {
    let p = json(sprintf('%J', policy));
    for (let k in ['dns','routing','policy','stats','fakedns']) if (p[k] != null) config[k] = p[k];
    config.outbounds = [];
    for (let o in p.outbounds) {
        if (o.protocol == 'selected-proxy') {
            let proxy = json(sprintf('%J', node.outbound));
            proxy.tag = o.tag;
            push(config.outbounds, proxy);
        } else push(config.outbounds, o);
    }
    config.inbounds[0].sniffing = { enabled: true, routeOnly: true, destOverride: ['http','tls','quic'] };
    if (p.fakedns != null) push(config.inbounds[0].sniffing.destOverride, 'fakedns');
    return config;
}
return { extract, apply };
