let fs = require('fs');
let parser = require('parser');
let generator = require('generator');
let upstream = require('upstream.subscription');
let state_dir = getenv('FX_STATE_DIR') || '/etc/forkop-xray';
let run_dir = getenv('FX_RUN_DIR') || '/var/run/forkop-xray';
let binary = getenv('FX_XRAY_BIN') || '/usr/libexec/forkop-xray/xray';
let cache_path = state_dir + '/subscription.json';
function quote(s) { return "'" + replace('' + s, /'/g, "'\\''") + "'"; }
function command(args) { return join(' ', map(args, quote)); }
function run(args) { return system(command(args) + ' >/dev/null 2>&1') == 0; }
function check_routing_config(path) {
    // Soft Go heap target, not an RSS guarantee. Routing lists can be large.
    // Prefer killing a failed oversized validator over the running router services.
    return run(['sh','-c','echo 1000 > /proc/self/oom_score_adj 2>/dev/null || :; exec "$@"',
        'forkop-xray-check','env','GOMEMLIMIT=128MiB','GOMAXPROCS=2',binary,'run','-test','-c',path]);
}
function read_json(path) { let s = fs.readfile(path); return s == null ? null : json(s); }
function write_json(path, value) {
    require('jsonfile').write(path, value);
}
function fingerprint(s) {
    let p = fs.popen('printf %s ' + quote(s) + ' | sha256sum', 'r');
    if (!p) die('Cannot calculate subscription identity');
    let v = p.read('all');
    if (p.close() != 0) die('Cannot calculate subscription identity');
    return split(trim(v), /\s+/)[0];
}
function settings() {
    let fixture = getenv('FX_SETTINGS');
    if (fixture) return read_json(fixture) || {};
    let uci = require('uci').cursor();
    let s = uci.get_all('forkop_xray', 'main') || {};
    // Missing option preserves the previously configured header exactly.
    if (s.hwid_enabled == '0') s.hwid = '';
    else if (s.hwid_enabled == '1' && !s.hwid) {
        let path = state_dir + '/device-hwid-short';
        let id = trim(fs.readfile(path) || '');
        if (!match(id, /^[a-f0-9]{4}(-[a-f0-9]{4}){3}$/)) {
            let mac = trim(fs.readfile('/sys/class/net/eth0/address') || fs.readfile('/sys/class/net/br-lan/address') || '');
            let model = trim(fs.readfile('/tmp/sysinfo/model') || '');
            if (!mac) mac = trim(fs.readfile(state_dir + '/device-hwid') || fs.readfile('/proc/sys/kernel/random/uuid') || '');
            if (!mac) die('Cannot generate device identity');
            let p = fs.popen('printf %s ' + quote(mac + '-' + model) + ' | md5sum', 'r');
            if (!p) die('Cannot calculate device identity');
            let hash = substr(trim(p.read('all') || ''), 0, 16);
            if (p.close() != 0 || !match(hash, /^[a-f0-9]{16}$/)) die('Cannot calculate device identity');
            id = substr(hash,0,4)+'-'+substr(hash,4,4)+'-'+substr(hash,8,4)+'-'+substr(hash,12,4);
            let temporary = path + '.' + id;
            if (!fs.writefile(temporary, id + '\n')) die('Cannot save device identity');
            fs.chmod(temporary, 0600);
            system(command(['ln', temporary, path]) + ' 2>/dev/null');
            fs.unlink(temporary);
            id = trim(fs.readfile(path) || '');
            if (!match(id, /^[a-f0-9]{4}(-[a-f0-9]{4}){3}$/)) die('Cannot commit device identity');
        }
        s.hwid = id;
    }
    if (!s.user_agent) {
        let p = fs.popen('/usr/libexec/forkop-xray/xray version 2>/dev/null','r');
        let output = p ? p.read('all') || '' : '';
        if (p) p.close();
        let version = match(output, /^Xray ([0-9]+\.[0-9]+\.[0-9]+)/);
        s.user_agent = 'Xray/' + (version ? version[1] : 'unknown');
    }
    return s;
}
function cache() { return read_json(cache_path); }
function selected(c) {
    if (c) for (let n in c.nodes || []) if (n.id == c.selected) return n;
    die('No selected node; update or import a subscription first');
}
function compiled(c, s) {
    if (c.routing_profile) {
        let profile = require('lists').expand(c.routing_profile, read_json(state_dir + '/rulesets.json'));
        return require('routing').compile(profile, selected(c), int(s.socks_port || 10808), c.nodes);
    }
    return { config: generator.generate(selected(c), s.socks_port, c.policy), urltest: null };
}
function config_for(c, s) { return compiled(c, s).config; }
function checked_result(c, s) {
    let result = compiled(c, s);
    let path = run_dir + '/candidate.json';
    write_json(path, result.config);
    result.config = null;
    let ok = check_routing_config(path);
    if (ok) result.config = read_json(path);
    fs.unlink(path);
    if (!ok) die('Xray rejected the candidate configuration; previous state retained');
    return result;
}
function checked_config(c, s) { return checked_result(c, s).config; }
function save(c) {
    let old = cache();
    if (old) {
        write_json(state_dir + '/previous.json.new', old);
        if (!fs.rename(state_dir + '/previous.json.new', state_dir + '/previous.json')) die('Cannot save rollback state');
    }
    write_json(cache_path + '.new', c);
    if (!fs.rename(cache_path + '.new', cache_path)) die('Cannot commit subscription');
}
function profile(s) { return fingerprint(sprintf('%J', [s.subscription_url || '', s.user_agent || 'v2rayN', s.hwid || ''])); }
function accept(body_path, headers_path, s, from_url) {
    let body = fs.readfile(body_path);
    let c = parser.parse(body);
    for (let n in c.nodes) { n.id = fingerprint(n.identity); delete n.identity; }
    let old = cache();
    // A new subscription source starts with its first supported node. Same source retains selection.
    let same = old && old.source == (from_url ? profile(s) : 'import');
    c.source = from_url ? profile(s) : 'import';
    if (same && old.policy) c.policy = old.policy;
    // Routing belongs to the router, not to a subscription URL or client user agent.
    if (old?.routing_profile) c.routing_profile = old.routing_profile;
    c.selected = same ? old.selected : c.nodes[0].id;
    let found = false;
    for (let n in c.nodes) if (n.id == c.selected) found = true;
    if (!found) {
        // A removed identity must not permanently prevent subscription refresh.
        // Prefer the same display name after provider key/endpoint rotation.
        let name;
        for (let n in old?.nodes || []) if (n.id == old.selected) name = n.name;
        c.selected = c.nodes[0].id;
        for (let n in c.nodes) if (name && n.name == name) { c.selected = n.id; break; }
    }
    c.updated = time();
    c.metadata = {};
    let meta = run_dir + '/metadata.json';
    if (upstream.extract_ui_metadata_file(headers_path, body_path, meta)) c.metadata = read_json(meta) || {};
    fs.unlink(meta);
    checked_config(c, s);
    // Avoid flash writes on unchanged successful automatic updates.
    if (!old || sprintf('%J', [old.source, old.nodes, old.skipped, old.metadata, old.selected, old.policy, old.routing_profile]) !=
        sprintf('%J', [c.source, c.nodes, c.skipped, c.metadata, c.selected, c.policy, c.routing_profile])) save(c);
    // Manual refresh time survives reboot without making automatic no-op polls write flash.
    if (ARGV[0] != 'update-due') {
        let stamp = state_dir + '/last-success-update';
        if (fs.writefile(stamp + '.new', '' + time())) {
            fs.chmod(stamp + '.new', 0600);
            fs.rename(stamp + '.new', stamp);
        }
    }
    fs.writefile(run_dir + '/last-success-update', '' + time());
    fs.writefile(run_dir + '/last-update', '' + time());
    print(sprintf('%J\n', { ok: true, supported: length(c.nodes), skipped: c.skipped, selection_changed: !found }));
}
function fetch(s) {
    let url = s.subscription_url || '';
    if (!match(url, /^https:\/\/[^[:space:]]+$/)) die('Subscription URL must use HTTPS');
    let ua = s.user_agent || 'v2rayN', hwid = s.hwid || '';
    if (match(ua + hwid, /[\r\n]/)) die('Invalid subscription header');
    if (hwid != '' && !match(hwid, /^[a-zA-Z0-9=-]{10,64}$/))
        die('Invalid HWID: use 10-64 Latin letters, digits, = or -. Clear custom HWID to use the router identity.');
    let body = run_dir + '/download.body', headers = run_dir + '/download.headers';
    // URL and credential headers are read from a private config, not curl process arguments.
    function curl_value(v) { return '"' + replace(replace(v, /\\/g, '\\\\'), /"/g, '\\"') + '"'; }
    let cfg = 'url = ' + curl_value(url) + '\nuser-agent = ' + curl_value(ua) + '\n';
    if (hwid != '') {
        cfg += 'header = ' + curl_value('X-HWID: ' + hwid) + '\n';
        let release = match(fs.readfile('/etc/openwrt_release') || '', /DISTRIB_RELEASE=['"]([^'"\r\n]+)['"]/);
        let os_version = release ? release[1] : 'unknown';
        let model = substr(trim(fs.readfile('/tmp/sysinfo/model') || 'OpenWrt router'), 0, 160);
        model = replace(model, /[\r\n]/g, ' ');
        cfg += 'header = ' + curl_value('X-Device-OS: OpenWrt Linux') + '\n';
        cfg += 'header = ' + curl_value('X-Ver-OS: ' + os_version) + '\n';
        cfg += 'header = ' + curl_value('X-Device-Model: ' + model) + '\n';
    }
    fs.writefile(run_dir + '/curl.conf', cfg); fs.chmod(run_dir + '/curl.conf', 0600);
    let args = ['curl', '--fail', '--silent', '--show-error', '--location', '--max-redirs', '3',
        '--ipv4', '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '15', '--max-time', '60',
        '--max-filesize', '2097152', '--compressed', '--noproxy', '*', '--config', run_dir + '/curl.conf',
        '--dump-header', headers, '--output', body];
    try {
        let report = run_dir + '/download.status';
        function download(options) {
            let rc=system(command(options)+' --write-out %{http_code} >'+quote(report)+' 2>/dev/null');
            let http=trim(fs.readfile(report) || '');fs.unlink(report);
            return {rc,http:match(http,/^[0-9]{3}$/)?http:'000'};
        }
        // Control-plane downloads do not depend on any subscription node.
        let result=download(args);
        if (result.rc != 0) die('Subscription download failed: curl=' + result.rc + ', HTTP=' + result.http + '; previous state retained');
        accept(body, headers, s, true);
    } catch (err) {
        fs.unlink(body); fs.unlink(headers); fs.unlink(run_dir + '/curl.conf');
        die(err.message);
    }
    fs.unlink(body); fs.unlink(headers); fs.unlink(run_dir + '/curl.conf');
}
function summary() {
    let c = cache(), s = settings();
    let output = { preview: true, mode: c?.routing_profile ? 'forkop-socks' : 'local-socks', socks: '127.0.0.1:' + (s.socks_port || '10808'),
        policy: c?.routing_profile ? 'forkop' : c ? (selected(c).policy ? 'subscription' : (c.policy ? 'template' : 'none')) : 'none',
        lan: read_json(run_dir + '/lan-status.json')?.active || false,
        selected: c?.selected || '', updated: c?.updated || 0, nodes: [], skipped: c?.skipped || [] };
    for (let n in c?.nodes || []) push(output.nodes, { id: n.id, name: n.name, selected: n.id == c.selected });
    print(sprintf('%J\n', output));
}
try {
    let action = ARGV[0] || 'status', s = settings();
    if (action == 'status' || action == 'nodes') summary();
    else if (action == 'update') fetch(s);
    else if (action == 'update-due') {
        let interval = int(s.update_interval || '3600');
        if (interval < 300) interval = 300;
        let last = int(fs.readfile(run_dir + '/last-update') || '0');
        if (s.enabled == '1' && s.subscription_url && time() - last >= interval) {
            // Rate-limit failed downloads as well as successful ones.
            fs.writefile(run_dir + '/last-update', '' + time());
            fetch(s);
        }
    } else if (action == 'import') {
        if (!ARGV[1]) die('Usage: forkop-xray import /path/to/subscription');
        let body = fs.readfile(ARGV[1]);
        if (body == null || length(body) > 2097152) die('Cannot read subscription file');
        accept(ARGV[1], '/dev/null', s, false);
    } else if (action == 'policy-import') {
        if (!ARGV[1]) die('Usage: forkop-xray policy-import TEMPLATE.json');
        let body = fs.readfile(ARGV[1]);
        if (body == null || length(body) > 2097152) die('Cannot read policy template');
        let c = cache(); if (!c) die('No cached subscription');
        c.policy = require('native_policy').extract(json(body), null);
        if (!c.policy) die('Subscription policy template has no DNS or routing');
        // Validate every node that will use the fallback before committing anything.
        let selection = c.selected;
        for (let n in c.nodes) { c.selected = n.id; checked_config(c, s); }
        c.selected = selection;
        save(c); summary();
    } else if (action == 'select') {
        let c = cache(); if (!c) die('No cached subscription');
        c.selected = ARGV[1] || '';
        checked_config(c, s); save(c); summary();
    } else if (action == 'routing-set') {
        if (!ARGV[1]) die('Usage: forkop-xray routing-set PROFILE.json');
        let body = fs.readfile(ARGV[1]);
        if (body == null || length(body) > 16777216) die('Cannot read routing profile');
        let c = cache(); if (!c) die('No cached subscription');
        c.routing_profile = json(body);
        if (c.routing_profile.lan && !fs.stat('/usr/libexec/forkop-xray/lan-integration-ready'))
            die('Routing: LAN activation is not installed; use routing-check first');
        checked_config(c, s); save(c); summary();
    } else if (action == 'routing-clear') {
        let c = cache(); if (!c) die('No cached subscription');
        delete c.routing_profile;
        checked_config(c, s); save(c); summary();
    } else if (action == 'routing-lists') {
        if (!ARGV[1]) die('Usage: forkop-xray routing-lists PROFILE.json');
        let body = fs.readfile(ARGV[1]);
        if (body == null || length(body) > 16777216) die('Cannot read routing profile');
        let cached = cache();
        let node = selected(cached);
        require('lists').refresh(json(body), state_dir, run_dir,
            getenv('FX_SRS_BIN') || '/usr/libexec/forkop-xray/forkop-srs-convert',
            s.socks_port || 10808, function(profile) {
                let result = require('routing').compile(profile,node,10818,cached.nodes);
                profile = null;
                let path = run_dir + '/ruleset-validation.json';
                write_json(path,result.config);
                result = null;
                gc();
                let valid = check_routing_config(path);
                fs.unlink(path);
                if (!valid) die('Xray rejected updated lists; previous cache retained');
            });
    } else if (action == 'routing-check') {
        if (!ARGV[1]) die('Usage: forkop-xray routing-check PROFILE.json');
        let body = fs.readfile(ARGV[1]);
        if (body == null || length(body) > 16777216) die('Cannot read routing profile');
        let cached = cache();
        let profile = require('lists').expand(json(body),read_json(state_dir + '/rulesets.json'));
        let result = require('routing').compile(profile, selected(cached), 10818, cached.nodes);
        let path = run_dir + '/routing-candidate.json';
        write_json(path + '.new.json', result.config);
        profile = null;
        result.config = null;
        gc();
        if (!check_routing_config(path + '.new.json')) {
            fs.unlink(path + '.new.json');
            die('Xray rejected routing configuration; active configuration unchanged');
        }
        if (!fs.rename(path + '.new.json', path)) die('Cannot save checked routing candidate');
        write_json(run_dir + '/routing-candidate-urltest.json', result.urltest);
        write_json(run_dir + '/routing-candidate-lan.json', result.lan);
        if (result.lan) fs.writefile(run_dir + '/routing-candidate.nft', result.lan.nft);
        else fs.unlink(run_dir + '/routing-candidate.nft');
        print(sprintf('%J\n', { ok: true, activated: false, config: path, warnings: result.warnings }));
    } else if (action == 'routing-refresh-due') {
        let c = cache();
        if (s.enabled == '1' && c?.routing_profile && length(require('lists').requested(c.routing_profile))) {
            let last = read_json(state_dir + '/rulesets.json')?.updated || 0;
            let attempt = int(fs.readfile(run_dir + '/last-list-attempt') || '0');
            if (time() - last >= 86400 && time() - attempt >= 3600) {
                fs.writefile(run_dir + '/last-list-attempt', '' + time());
                require('lists').refresh(c.routing_profile, state_dir, run_dir,
                    getenv('FX_SRS_BIN') || '/usr/libexec/forkop-xray/forkop-srs-convert',
                    s.socks_port || 10808, function(profile) {
                        let result = require('routing').compile(profile, selected(c), int(s.socks_port || 10808), c.nodes);
                        profile = null;
                        let path = run_dir + '/ruleset-validation.json';
                        write_json(path, result.config);
                        result = null;
                        gc();
                        let valid = check_routing_config(path); fs.unlink(path);
                        if (!valid) die('Xray rejected updated lists; previous cache retained');
                    });
            }
        }
    } else if (action == 'routing-tick') {
        let c = cache();
        if (s.enabled == '1' && c?.routing_profile?.urltest)
            require('urltest_runtime').tick(run_dir, binary);
    } else if (action == 'routing-urltest') {
        require('urltest_runtime').tick(run_dir, binary);
    } else if (action == 'prepare') {
        let c = cache();
        let result = checked_result(c, s);
        let config = result.config;
        let manifest = result.urltest;
        write_json(run_dir + '/config.json.new', config);
        if (!fs.rename(run_dir + '/config.json.new', run_dir + '/config.json')) die('Cannot install runtime config');
        write_json(run_dir + '/routing-urltest.json', manifest);
        write_json(run_dir + '/routing-lan.json', result.lan);
    } else if (action == 'rollback') {
        let c = read_json(state_dir + '/previous.json');
        if (!c) die('No previous subscription');
        checked_config(c, s); save(c); summary();
    } else die('Usage: forkop-xray status|nodes|update|import FILE|policy-import TEMPLATE.json|select ID|prepare|rollback|routing-set PROFILE.json|routing-clear|routing-tick|routing-refresh-due|routing-check PROFILE.json|routing-lists PROFILE.json|routing-urltest');
} catch (err) {
    // Runtime/parsing exceptions can include payloads. Emit only known operational errors.
    let message = split(err.message || 'Operation failed', '\n')[0];
    if (!match(message, /^(Lists: |URLTest: |Routing: |Subscription |Invalid subscription header|Xray rejected|Selected node |No selected node|No supported |No cached |No previous |Cannot |Usage:|Unsupported subscription format|Expected Xray|Empty or oversized|Too many )/))
        message = 'Operation failed; previous state retained';
    warn('Forkop-Xray: ', message, '\n'); exit(1);
}
