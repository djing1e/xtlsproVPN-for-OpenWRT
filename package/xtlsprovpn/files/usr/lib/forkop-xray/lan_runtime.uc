// Own only our inet table, exact fwmark rules and exact local routes.
let fs = require('fs');
function fail(s) { die('LAN: ' + s); }
function quote(s) { return "'" + replace('' + s, /'/g, "'\\''") + "'"; }
function command(args) { return join(' ', map(args, quote)); }
function run(args) { return system(command(args) + ' >/dev/null 2>&1') == 0; }
function output(args) {
    let p = fs.popen(command(args) + ' 2>/dev/null', 'r');
    if (!p) return null;
    let s = p.read('all'); return p.close() == 0 ? s : null;
}
function read(path) { let s = fs.readfile(path); return s == null ? null : json(s); }
function write(path, value) {
    if (!fs.writefile(path + '.new', sprintf('%J', value))) fail('cannot save ownership state');
    fs.chmod(path + '.new', 0600);
    if (!fs.rename(path + '.new', path)) fail('cannot commit ownership state');
}
function state_path(dir) { return dir + '/lan-owned.json'; }
function checked_plan(plan) {
    // Regenerate firewall text from validated scope instead of executing stored text.
    if (plan?.version != 1 || plan.table != 'forkop_xray' || plan.route_table != 51880 ||
        plan.rule_priority != 104 || plan.mark != '0x08000000') fail('invalid LAN manifest');
    let dummy = { inbounds: [], routing: { rules: [] } };
    return require('transparent').attach(dummy, {interface: plan.interface, client_mac: plan.client_mac});
}
function cleanup(dir) {
    let path = state_path(dir), state = read(path);
    if (state == null) return;
    if (state.version != 1) fail('unknown ownership state');
    // Stop interception before removing policy routing. Preserve failed entries for retry.
    if (state.nft) {
        if (run(['nft','list','table','inet','forkop_xray']) &&
            !run(['nft','delete','table','inet','forkop_xray'])) fail('cannot remove owned nft table');
        state.nft = false; write(path, state);
    }
    let errors = false;
    for (let family in ['-4','-6']) {
        let item = state[family];
        if (!item) continue;
        if (item.rule) {
            let rules = output(['ip',family,'rule','show']);
            if (rules == null) { errors = true; continue; }
            if (match(rules, /(^|\n)104:/) && !run(['ip',family,'rule','del','pref','104',
                'fwmark','0x08000000/0x08000000','lookup','51880'])) { errors = true; continue; }
            item.rule = false; write(path, state);
        }
        if (item.route) {
            let routes = output(['ip',family,'route','show','table','51880']);
            if (routes != null && trim(routes) != '' && !run(['ip',family,'route','del','local',
                family == '-4' ? '0.0.0.0/0' : '::/0','dev','lo','table','51880'])) { errors = true; continue; }
            item.route = false; write(path, state);
        }
    }
    if (errors) fail('owned route cleanup incomplete; retry stop');
    fs.unlink(path);
    write(dir + '/lan-status.json', {active:false});
}
function preflight(plan, dir) {
    if (run(['/etc/init.d/forkop','running'])) fail('original Forkop is running; no changes made');
    if (run(['nft','list','table','inet','forkop_xray'])) fail('nft table name is occupied');
    for (let family in ['-4','-6']) {
        let rules = output(['ip',family,'rule','show']);
        if (rules == null) fail('cannot inspect policy rules');
        if (match(rules, /(^|\n)104:/) || index(rules,'0x8000000') >= 0 || index(rules,'51880') >= 0)
            fail('reserved rule priority, mark or table is occupied');
        let routes = output(['ip',family,'route','show','table','51880']);
        if (routes != null && trim(routes) != '') fail('reserved route table is occupied');
    }
    if (!run(['ip','link','show','dev',plan.interface])) fail('LAN interface is unavailable');
    for (let option in ['flow_offloading','flow_offloading_hw']) {
        if (trim(output(['uci','-q','get','firewall.@defaults[0].' + option]) || '') == '1')
            fail('flow offloading must be disabled before LAN activation');
    }
    // Both wildcard listeners require dual-stack sockets on this host.
    if (trim(fs.readfile('/proc/sys/net/ipv6/bindv6only') || '1') != '0')
        fail('dual-stack sockets are unavailable');
    if (!fs.writefile(dir + '/lan-rules.nft', plan.nft)) fail('cannot write nft candidate');
    // Keep nft's diagnostic visible: a generic error hides the failing rule.
    if (system(command(['nft','-c','-f',dir + '/lan-rules.nft'])) != 0)
        fail('kernel rejected nft candidate');
}
function apply(plan, dir, core_pid) {
    plan = checked_plan(plan);
    preflight(plan, dir);
    let path = state_path(dir);
    let owned = {version:1, nft:false, '-4':{route:false,rule:false}, '-6':{route:false,rule:false}};
    write(path, owned);
    try {
        for (let family in ['-4','-6']) {
            if (!run(['ip',family,'route','add','local',family == '-4' ? '0.0.0.0/0' : '::/0',
                'dev','lo','table','51880'])) fail('cannot create local route');
            owned[family].route = true; write(path, owned);
            if (!run(['ip',family,'rule','add','pref','104','fwmark','0x08000000/0x08000000',
                'lookup','51880'])) fail('cannot create policy rule');
            owned[family].rule = true; write(path, owned);
        }
        if (!run(['nft','-f',dir + '/lan-rules.nft'])) fail('cannot install nft table');
        owned.nft = true; write(path, owned);
        write(dir + '/lan-status.json', {active:true, core_pid, scope:plan.client_mac,
            interface:plan.interface, signature:sprintf('%J',plan)});
    } catch (err) { cleanup(dir); die(err.message); }
}
function tick(dir) {
    let plan = read(dir + '/routing-lan.json');
    if (!plan) { cleanup(dir); return; }
    let services = output(['ubus','-t','2','call','service','list','{"name":"forkop-xray"}']);
    let instance = services == null ? null : json(services)?.['forkop-xray']?.instances?.core;
    if (!plan || !instance?.running || !instance.pid) { cleanup(dir); return; }
    if (instance.command?.[0] != '/usr/libexec/forkop-xray/xray' ||
        instance.command?.[3] != '/var/run/forkop-xray/config.json') {
        cleanup(dir); fail('unexpected running core command');
    }
    plan = checked_plan(plan);
    let state = read(dir + '/lan-status.json');
    if (state?.active && state.core_pid == instance.pid && state.signature == sprintf('%J',plan) &&
        run(['nft','list','table','inet','forkop_xray'])) return;
    cleanup(dir);
    apply(plan, dir, instance.pid);
}
return { apply, cleanup, tick, preflight };
