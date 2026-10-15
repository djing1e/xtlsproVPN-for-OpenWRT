// GPL-2.0-or-later. Native Xray subscription path, independent of sing-box conversion.
let ip = require('core.ip');

function decode(s) {
    s = '' + (s || '');
    let out = '';
    for (let i = 0; i < length(s); i++) {
        if (substr(s, i, 1) == '%') {
            let h = substr(s, i + 1, 2);
            if (!match(h, /^[0-9a-fA-F]{2}$/)) die('Invalid percent escape');
            let n = int(h, 16);
            if (n < 32 || n == 127) die('Control character in URI');
            out += chr(n); i += 2;
        } else out += substr(s, i, 1); // Literal + must survive ML-KEM/URI values.
    }
    return out;
}
function key_valid(s) {
    if (type(s) != 'string' || !match(s, /^[A-Za-z0-9_-]{43}$/)) return false;
    return length(b64dec(replace(replace(s, /-/g, '+'), /_/g, '/') + '=')) == 32;
}
function normalize(o, name) {
    if (type(o) != 'object' || o.protocol != 'vless') die('Only VLESS is supported');
    let next = o.settings?.vnext;
    if (type(next) != 'array' || length(next) != 1 || length(next[0].users || []) != 1)
        die('Expected one VLESS endpoint and one user');
    let n = next[0], u = n.users[0], s = o.streamSettings || {}, r = s.realitySettings || {};
    let host = '' + (n.address || '');
    if (!(ip.valid_ip(host) || (length(host) <= 253 && match(host, /^[A-Za-z0-9][A-Za-z0-9.-]*$/)))) die('Invalid server address');
    if (type(n.port) != 'int' || n.port < 1 || n.port > 65535) die('Invalid server port');
    if (!match(u.id || '', /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/)) die('Invalid UUID');
    if (s.network != 'tcp' && s.network != 'raw') die('Only TCP/RAW is supported in this preview');
    if (s.security != 'reality') die('Only REALITY is supported in this preview');
    let encryption = u.encryption || 'none';
    if (encryption != 'none' && !match(encryption, /^mlkem768x25519plus\.native\.(0rtt|1rtt)\.[A-Za-z0-9_.+-]+$/))
        die('Unsupported VLESS encryption');
    let flow = u.flow || '';
    if (flow != '' && flow != 'xtls-rprx-vision') die('Unsupported VLESS flow');
    let pbk = r.password || r.publicKey || '';
    if (!key_valid(pbk)) die('Invalid REALITY client key');
    let sid = r.shortId || '';
    if (length(sid) > 16 || length(sid) % 2 || !match(sid, /^[0-9a-fA-F]*$/)) die('Invalid REALITY shortId');
    let sni = r.serverName || '';
    if (!match(sni, /^[A-Za-z0-9][A-Za-z0-9.-]*$/)) die('Missing or invalid REALITY SNI');
    let fp = r.fingerprint || 'chrome';
    if (!match(fp, /^[A-Za-z0-9_-]+$/)) die('Invalid fingerprint');
    if (o.proxySettings || s.sockopt || o.mux || r.mldsa65Verify || s.tcpSettings || s.rawSettings)
        die('Advanced outbound options are not supported in this preview');
    let spx = r.spiderX || '/';
    if (substr(spx, 0, 1) != '/') die('spiderX must start with /');
    let outbound = { tag: 'proxy', protocol: 'vless', settings: { vnext: [{ address: host, port: n.port,
        users: [{ id: lc(u.id), encryption, flow }] }] }, streamSettings: { network: 'raw', security: 'reality',
        realitySettings: { serverName: sni, fingerprint: fp, publicKey: pbk, shortId: lc(sid), spiderX: spx } } };
    // Identity excludes display name and rotating keys. Full identity is compared, no hash collisions.
    let identity = sprintf('%J', [lc(host), n.port, lc(u.id), lc(sni)]);
    return { name: name || host, identity, outbound };
}
function uri(line) {
    let m = match(line, /^vless:\/\/([^@/?#]+)@(\[[^\]]+\]|[^:/?#]+):([0-9]+)\?([^#]*)(#(.*))?$/);
    if (!m) die('Unsupported or malformed VLESS URI');
    let host = m[2];
    if (substr(host, 0, 1) == '[') host = substr(host, 1, length(host) - 2);
    let q = {};
    for (let pair in split(m[4], '&')) {
        if (pair == '') continue;
        let eq = index(pair, '=');
        let k = decode(eq < 0 ? pair : substr(pair, 0, eq));
        if (q[k] != null) die('Duplicate URI parameter');
        q[k] = decode(eq < 0 ? '' : substr(pair, eq + 1));
    }
    let allowed = ['encryption','flow','type','security','sni','fp','pbk','sid','spx','headerType'];
    for (let k in keys(q)) if (index(allowed, k) < 0) die('Unsupported URI parameter');
    if (q.headerType && q.headerType != 'none') die('TCP header camouflage is unsupported');
    return normalize({ protocol: 'vless', settings: { vnext: [{ address: host, port: int(m[3]), users: [{
        id: decode(m[1]), encryption: q.encryption || 'none', flow: q.flow || '' }] }] }, streamSettings: {
        network: q.type || 'tcp', security: q.security || '', realitySettings: { serverName: q.sni,
        fingerprint: q.fp, publicKey: q.pbk, shortId: q.sid, spiderX: q.spx } } }, decode(m[6] || host));
}
function parse(body) {
    if (type(body) != 'string' || length(body) > 2097152) die('Empty or oversized subscription');
    body = trim(body);
    if (!match(body, /^[\[{]/) && index(body, '://') < 0) {
        let b = replace(replace(replace(body, /\s/g, ''), /-/g, '+'), /_/g, '/');
        while (length(b) % 4) b += '=';
        body = b64dec(b);
        if (body == null) die('Unsupported subscription format');
        body = trim(body);
    }
    let nodes = [], skipped = [], entries = [];
    if (match(body, /^[\[{]/)) {
        let data = json(body);
        let configs = type(data) == 'array' ? data : [data];
        for (let c in configs) {
            if (type(c) != 'object') die('Invalid Xray JSON subscription');
            if (c.protocol) push(entries, { o: c, name: c.tag });
            else if (type(c.outbounds) == 'array') {
                for (let o in c.outbounds) {
                    if (o.protocol == 'freedom' || o.protocol == 'blackhole' || o.protocol == 'dns') continue;
                    push(entries, { o, name: c.remarks || c.remark || o.tag, profile: c });
                }
            } else die('Expected Xray profiles or VLESS URI subscription');
        }
    } else {
        for (let line in split(body, '\n')) {
            line = trim(line);
            if (line == '' || substr(line, 0, 1) == '#') continue;
            push(entries, { line });
        }
    }
    if (length(entries) > 1000) die('Too many subscription nodes');
    for (let i, e in entries) {
        try {
            let n = e.line != null ? uri(e.line) : normalize(e.o, e.name);
            if (e.profile) n.policy = require('native_policy').extract(e.profile, e.o.tag);
            let existing = null;
            for (let p in nodes) if (p.identity == n.identity) existing = p;
            if (existing) {
                if (sprintf('%J', [existing.outbound, existing.policy]) != sprintf('%J', [n.outbound, n.policy])) die('Ambiguous duplicate endpoint');
                continue;
            }
            push(nodes, n);
        } catch (err) {
            if (e.profile?.routing != null || e.profile?.dns != null || e.profile?.policy != null || e.profile?.fakedns != null || e.profile?.stats != null)
                die('Subscription policy validation failed; previous state retained');
            // Do not expose the source URI, UUID, encryption or publicKey in diagnostics.
            push(skipped, { entry: i + 1, reason: split(err.message || 'Invalid node', '\n')[0] });
        }
    }
    if (!length(nodes)) die('No supported VLESS TCP/RAW + REALITY nodes');
    return { schema: 1, nodes, skipped };
}
return { parse, uri, normalize };
