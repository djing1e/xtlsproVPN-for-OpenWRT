// Same community assets as the original Forkop. All selected lists form one
// validated transaction; any failed fetch/decode/config check retains old cache.
let fs = require('fs');
let routing = require('routing');
let supported = ['russia_inside','porn','news','youtube','discord','google_ai','meta',
    'twitter','hdrezka','tiktok','telegram','cloudflare','google_play','hodca','ads_hagezi_pro'];
function fail(s) { die('Lists: ' + s); }
function quote(s) { return "'" + replace('' + s, /'/g, "'\\''") + "'"; }
function run(args) { return system(join(' ',map(args,quote))+' >/dev/null 2>&1') == 0; }
function url(name) {
    let known = false;
    for (let item in supported) if (item == name) known = true;
    if (!known) fail('unsupported community list');
    return name == 'ads_hagezi_pro'
        ? 'https://github.com/zxc-rv/ad-filter/releases/latest/download/adlist.srs'
        : 'https://github.com/itdoginfo/allow-domains/releases/latest/download/' + name + '.srs';
}
function requested(profile) {
    if (type(profile?.sections) != 'array') fail('profile has no sections');
    let result = [], seen = {};
    for (let section in profile.sections) {
        let names = section.community_lists || [];
        if (type(names) != 'array') fail('community_lists must be an array');
        for (let name in names) {
            url(name);
            if (!seen[name]) { seen[name] = true; push(result,name); }
        }
    }
    return result;
}
function expand(profile, cache) {
    let result = json(sprintf('%J',profile));
    requested(result);
    for (let section in result.sections) {
        if (section.rules == null) section.rules = [];
        if (type(section.rules) != 'array') fail('section rules must be an array');
        for (let name in section.community_lists || []) {
            let list = cache?.lists?.[name];
            if (cache?.version != 1 || list?.url != url(name) || type(list?.rules) != 'array' || !length(list.rules))
                fail('missing validated list ' + name);
            for (let rule in list.rules) push(section.rules,rule);
        }
        delete section.community_lists;
    }
    return result;
}
function refresh(profile, state_dir, run_dir, converter, socks_port, validate) {
    let names = requested(profile);
    if (!length(names)) fail('no community lists selected');
    socks_port = int(socks_port);
    if (socks_port < 1024 || socks_port > 65535) fail('invalid download proxy port');
    let next = {version:1, updated:time(), lists:{}};
    let raw = run_dir + '/ruleset-download.srs', decoded = run_dir + '/ruleset-decoded.json';
    try {
        for (let name in names) {
            let source = url(name);
            if (!run(['curl','--fail','--silent','--location','--max-redirs','3',
                '--proto','=https','--proto-redir','=https','--connect-timeout','10','--max-time','45',
                '--max-filesize','8388608','--noproxy','','--proxy','socks5h://127.0.0.1:'+socks_port,
                '--output',raw,source])) fail('download failed for ' + name + '; previous cache retained');
            fs.unlink(decoded);
            if (!run([converter,raw,decoded])) fail('SRS conversion failed for ' + name + '; previous cache retained');
            let data = fs.readfile(decoded);
            if (data == null || length(data) > 33554432) fail('invalid decoded list size');
            next.lists[name] = {url:source, rules:routing.source_rules(json(data))};
        }
        let path = state_dir + '/rulesets.json';
        let updated = next.updated;
        require('jsonfile').write(path+'.new', next);
        let expanded = expand(profile,next);
        next = null;
        // Transfer ownership into the callback: its compiler can release the
        // expanded lists before starting Xray. Keep no caller-side reference.
        let pending = [expanded]; expanded = null;
        validate(pop(pending));
        // Commit only after the same real Xray validation as before.
        if (!fs.rename(path+'.new',path)) fail('cannot commit lists');
        print(sprintf('%J\n',{ok:true,activated:false,lists:names,updated}));
    } catch (err) {
        fs.unlink(raw); fs.unlink(decoded);
        fs.unlink(state_dir + '/rulesets.json.new');
        die(err.message);
    }
    fs.unlink(raw); fs.unlink(decoded);
}
return {url, requested, expand, refresh};
