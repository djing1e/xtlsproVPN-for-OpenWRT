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
    let xhttp = s.network == 'xhttp' || s.network == 'splithttp';
    if (!xhttp && s.network != 'tcp' && s.network != 'raw') die('Unsupported VLESS transport');
    if (!xhttp && s.security != 'reality') die('TCP/RAW requires REALITY');
    if (xhttp && index(['tls','reality','none'],s.security || 'none')<0) die('Unsupported XHTTP security');
    let encryption = u.encryption || 'none';
    if (encryption != 'none' && !match(encryption, /^mlkem768x25519plus\.native\.(0rtt|1rtt)\.[A-Za-z0-9_.+-]+$/))
        die('Unsupported VLESS encryption');
    let flow = u.flow || '';
    if (flow != '' && flow != 'xtls-rprx-vision') die('Unsupported VLESS flow');
    if (xhttp) {
        if (flow != '') die('XHTTP requires an empty VLESS flow');
        if (o.proxySettings || s.sockopt || o.mux) die('Advanced outbound options are unsupported');
        let x = s.xhttpSettings || s.splithttpSettings || {};
        if (type(x)!='object' || length(sprintf('%J',x))>65536) die('Invalid XHTTP settings');
        let path=x.path || '/', mode=x.mode || 'auto', http_host=x.host || '';
        if (type(path)!='string' || substr(path,0,1)!='/' || match(path,/[\r\n]/)) die('Invalid XHTTP path');
        if (index(['auto','packet-up','stream-up','stream-one'],mode)<0) die('Invalid XHTTP mode');
        if (type(http_host)!='string' || match(http_host,/[\r\n]/)) die('Invalid XHTTP host');
        let security=s.security || 'none';
        let stream={network:'xhttp',security,xhttpSettings:json(sprintf('%J',x))};
        stream.xhttpSettings.path=path; stream.xhttpSettings.mode=mode;
        let sni='';
        if (security=='tls') {
            let tls=s.tlsSettings || {};
            if (type(tls)!='object' || length(sprintf('%J',tls))>65536) die('Invalid TLS settings');
            sni=tls.serverName || '';
            if (type(sni)!='string' || (sni && !match(sni,/^[A-Za-z0-9][A-Za-z0-9.-]*$/))) die('Invalid TLS SNI');
            if (tls.alpn!=null && (type(tls.alpn)!='array' || length(filter(tls.alpn,v=>type(v)!='string' || match(v,/[\r\n]/)))>0)) die('Invalid TLS ALPN');
            stream.tlsSettings=json(sprintf('%J',tls));
        } else if (security=='reality') {
            if (!key_valid(r.password || r.publicKey || '')) die('Invalid REALITY client key');
            sni=r.serverName || '';
            if (!match(sni,/^[A-Za-z0-9][A-Za-z0-9.-]*$/)) die('Missing or invalid REALITY SNI');
            if (length(r.shortId || '')>16 || length(r.shortId || '')%2 || !match(r.shortId || '',/^[a-fA-F0-9]*$/)) die('Invalid REALITY shortId');
            stream.realitySettings=json(sprintf('%J',r));
        }
        let outbound={tag:'proxy',protocol:'vless',settings:{vnext:[{address:host,port:n.port,
            users:[{id:lc(u.id),encryption,flow:''}]}]},streamSettings:stream};
        // Paths and transport distinguish hosts sharing the same address and UUID.
        let identity=sprintf('%J',[lc(host),n.port,lc(u.id),lc(sni),'xhttp',security,http_host,path,mode]);
        return {name:name || host,identity,outbound};
    }
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
        let raw = eq < 0 ? '' : substr(pair, eq + 1);
        // Form-encoded JSON may use + for spaces; literal + remains intact in keys/encryption/path.
        q[k] = decode(k=='extra' ? replace(raw, /\+/g, ' ') : raw);
    }
    let allowed = ['encryption','flow','type','security','sni','fp','pbk','sid','spx','headerType','host','path','mode','extra','alpn','allowInsecure','insecure'];
    for (let k in keys(q)) if (index(allowed, k) < 0) die('Unsupported URI parameter');
    if (q.headerType && q.headerType != 'none') die('TCP header camouflage is unsupported');
    let transport=q.type || 'tcp';
    let stream={network:transport,security:q.security || '',realitySettings:{serverName:q.sni,
        fingerprint:q.fp,publicKey:q.pbk,shortId:q.sid,spiderX:q.spx}};
    if (transport=='xhttp' || transport=='splithttp') {
        let x={host:q.host || '',path:q.path || '/',mode:q.mode || 'auto'};
        if (q.extra) {
            if (length(q.extra)>65536) die('Oversized XHTTP extra');
            let extra;
            try { extra=json(q.extra); } catch(e) { die('Invalid XHTTP extra JSON'); }
            if (type(extra)!='object') die('Invalid XHTTP extra JSON');
            x.extra=extra;
        }
        stream.xhttpSettings=x;
        stream.tlsSettings={};
        if (q.sni) stream.tlsSettings.serverName=q.sni;
        if (q.fp) stream.tlsSettings.fingerprint=q.fp;
        if (q.alpn) stream.tlsSettings.alpn=split(q.alpn,',');
        if (q.allowInsecure!=null || q.insecure!=null) {
            let insecure=q.allowInsecure ?? q.insecure;
            if (index(['0','1','true','false'],insecure)<0) die('Invalid TLS verification option');
            stream.tlsSettings.allowInsecure=insecure=='1' || insecure=='true';
        }
    } else {
        for (let k in ['host','path','mode','extra','alpn','allowInsecure','insecure'])
            if (q[k]!=null) die('Transport parameter requires XHTTP');
    }
    return normalize({protocol:'vless',settings:{vnext:[{address:host,port:int(m[3]),users:[{
        id:decode(m[1]),encryption:q.encryption || 'none',flow:q.flow || ''}]}]},streamSettings:stream},decode(m[6] || host));
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
    if (!length(nodes)) die('No supported VLESS nodes (TCP/REALITY or XHTTP)');
    return { schema: 1, nodes, skipped };
}
return { parse, uri, normalize };
