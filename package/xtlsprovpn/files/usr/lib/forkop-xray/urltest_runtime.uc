let fs = require('fs');
let policy = require('urltest');
function fail(message) { die('URLTest: ' + message); }
function quote(s) { return "'" + replace('' + s, /'/g, "'\\''") + "'"; }
function output(args) {
    let pipe = fs.popen(join(' ', map(args, quote)) + ' 2>/dev/null', 'r');
    if (!pipe) return null;
    let result = pipe.read('all');
    return pipe.close() == 0 ? result : null;
}
function tick(run_dir, binary) {
    let text = fs.readfile(run_dir + '/routing-urltest.json');
    if (text == null) fail('no checked routing plan');
    let manifest = json(text);
    if (manifest?.version != 1 || manifest.api != '127.0.0.1:10820' || manifest.balancer != 'urltest-main')
        fail('URLTest is not configured');
    let opts = policy.options(manifest.options);
    let peers = manifest.peers;
    if (type(peers) != 'array' || !length(peers) || length(peers) > 32) fail('invalid candidates');
    let known = {};
    for (let peer in peers) {
        if (!match(peer.id || '', /^[a-f0-9]{64}$/) || peer.tag != 'node-' + peer.id ||
            peer.port < 11000 || peer.port > 11031 || known[peer.tag]) fail('invalid candidate');
        known[peer.tag] = true;
    }
    function api(method, args) {
        let command = [binary, 'api', method, '--server=' + manifest.api, '-timeout', '3', '-json'];
        for (let arg in args || []) push(command, arg);
        let result = output(command);
        if (result == null) fail('Xray API unavailable; selection unchanged');
        if (method == 'bo' && trim(result) == '') return {};
        return json(result);
    }
    let info = api('bi', [manifest.balancer]);
    let current = info.balancer?.override?.target || info.balancer?.principleTarget?.tag?.[0];
    if (!known[current]) fail('running core does not match checked candidates');
    let listed = api('lso'), present = {};
    for (let outbound in listed.outbounds || []) present[outbound.tag] = true;
    for (let peer in peers) if (!present[peer.tag]) fail('running core is missing a checked candidate');
    let stats = api('statsquery', ['-pattern', manifest.counter_prefix]);
    let traffic = 0;
    for (let stat in stats.stat || [])
        if (stat.name == manifest.counter_prefix + 'uplink' || stat.name == manifest.counter_prefix + 'downlink')
            traffic += int(stat.value || 0);
    let state_path = run_dir + '/urltest-state.json';
    let previous = fs.readfile(state_path), state = previous == null ? {} : json(previous);
    // A changed candidate plan starts a new measurement cycle.
    let signature = sprintf('%J', manifest);
    if (state.plan != signature) state = { plan: signature };
    let decision = policy.due(state, time(), traffic, opts);
    state = decision.state;
    let samples = [];
    if (decision.run) {
        for (let peer in peers) {
            let result = output(['curl', '--silent', '--fail', '--location', '--max-redirs', '2',
                '--connect-timeout', '3', '--max-time', '5', '--max-filesize', '4096',
                '--proto', '=https', '--proto-redir', '=https', '--noproxy', '',
                '--socks5-hostname', '127.0.0.1:' + peer.port, '--output', '/dev/null',
                '--write-out', '%{time_total}', opts.testing_url]);
            let ms = result != null && match(trim(result), /^[0-9]+([.][0-9]+)?$/)
                ? int(trim(result) * 1000) : null;
            push(samples, { tag: peer.tag, ms });
        }
        let chosen = policy.choose(current, samples, opts.tolerance_ms);
        if (chosen != current) {
            // This changes only the balancer override. No restart or config rewrite.
            api('bo', ['-b', manifest.balancer, chosen]);
            current = chosen;
        }
        state.last_check = time(); state.samples = samples;
    }
    state.current = current; state.idle = decision.idle;
    if (!fs.writefile(state_path + '.new', sprintf('%J\n', state))) fail('cannot save test state');
    fs.chmod(state_path + '.new', 0600);
    if (!fs.rename(state_path + '.new', state_path)) fail('cannot commit test state');
    print(sprintf('%J\n', { ok: true, tested: decision.run, idle: state.idle, current }));
}
return { tick };
