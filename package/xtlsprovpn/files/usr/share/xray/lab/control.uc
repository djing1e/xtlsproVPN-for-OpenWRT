#!/usr/bin/ucode
import * as fs from 'fs';
import { cursor } from 'uci';
import { operation_lock, config, snapshot, save, load, run_dir, uptime, capture, health_check, latencies, diagnose, job, redacted_logs } from './state.mjs';
import { decide } from './watchdog.uc';

const action=ARGV[0] || 'status';
let output;
switch (action) {
case 'status': output=snapshot(); break;
case 'lock': output=operation_lock(); break;
case 'health': output=health_check(); break;
case 'latency': output=latencies(); break;
case 'diagnose': output=diagnose(); break;
case 'diagnostics': output=load(run_dir+'/diagnostics.json') || {checks:[]}; break;
case 'logs': output=redacted_logs(); break;
case 'job': output=job(); break;
case 'jobset': {
    const previous=load(run_dir+'/job.json') || {};
    const id=ARGV[1]=='pending'?trim(fs.readfile('/proc/sys/kernel/random/uuid') || ''+time()):previous.id || '';
    save(run_dir+'/job.json',{id,state:ARGV[1],action:ARGV[2],pid:int(ARGV[3]),updated:time(),
        message:ARGV[1]=='failed'?'Операция не завершилась. Откройте диагностику.':ARGV[1]=='done'?'Операция завершена.':'Выполняется…'});
    exit(0);
}
case 'stage': {
    const directory=ARGV[1], requested=ARGV[2] || '';
    let c=cursor(directory); c.load('xray_core');
    const all=c.get_all('xray_core') || {}, g=all.general || {};
    const nodes=sort(filter(keys(all),k=>all[k]['.type']=='servers'));
    if (!length(nodes)) die('No imported subscription nodes');
    let mode=requested=='auto'?'auto':requested?'manual':g.fx_mode || 'manual';
    let location=requested && requested!='auto'?requested:g.fx_location || g.tcp_balancer_v4?.[0] || nodes[0];
    if (index(nodes,location)<0) die('Unknown location');
    for (let key,value in {fx_dashboard:'1',fx_mode:mode,fx_location:location,
        fx_probe_url:g.fx_probe_url || 'https://cp.cloudflare.com/generate_204',
        fx_probe_interval:g.fx_probe_interval || '60',fx_watchdog_enabled:g.fx_watchdog_enabled || '1',
        fx_watch_interface:g.fx_watch_interface || 'lan',fx_watch_delay:g.fx_watch_delay || '2000',
        tcp_balancer_v4:mode=='auto'?nodes:[location],udp_balancer_v4:mode=='auto'?nodes:[location]})
        c.set('xray_core','general',key,value);
    const lan=capture(['ubus','call','network.interface.lan','status']);
    if (lan.ok) {
        let network=json(lan.text), device=network.l3_device, address=network['ipv4-address']?.[0];
        if (network.up && match(device || '',/^[A-Za-z0-9_.-]{1,15}$/) && address) {
            for (let key,value in {lab_iface:device,lab_address:address.address,lab_mask:''+address.mask,tproxy_ifaces_v4:[device]})
                c.set('xray_core','general',key,value);
        }
    }
    if (!c.commit('xray_core')) die('Cannot save staged settings');
    fs.chmod(directory+'/xray_core',0600); exit(0);
}
case 'watch-step': {
    const s=snapshot(), g=config().general || {}, before=load(run_dir+'/watchdog.json') || {};
    const now=uptime();
    const busy=s.operation_busy || index(['pending','running'],s.job.state)>=0;
    let h=s.health, fresh=false;
    if (g.fx_watchdog_enabled=='1' && s.enabled && s.autostart && s.interface.up && s.core.running && !busy &&
        (!before.probe_at || now-before.probe_at>=60 || before.probe_pid!=s.core.pid)) {
        h=health_check(); fresh=true; before.probe_at=now; before.probe_pid=s.core.pid;
    }
    const old_recovery=before.last_recovery,old_outages=before.outages || 0;
    const r=decide(before,{now,enabled:g.fx_watchdog_enabled=='1',desired:s.enabled && s.autostart,
        interface_up:s.interface.up,signature:s.interface.signature,settle:max(1,int((int(g.fx_watch_delay || 2000)+999)/1000)),
        busy,core:s.core.running,interception:s.interception.active,probe_new:fresh,
        proxy_ok:h?.proxy_ok===true,direct_ok:h?.direct_ok===true});
    if (r.state.last_recovery!=null && r.state.last_recovery!=old_recovery) r.state.recovery_at=time();
    if ((r.state.outages || 0)>old_outages) r.state.outage_at=time();
    r.state.reason=r.reason; r.state.checked=time(); r.state.enabled=g.fx_watchdog_enabled=='1';
    save(run_dir+'/watchdog.json',r.state);
    if (r.action) print(r.action+'\n');
    exit(0);
}
default: die('Unknown dashboard operation');
}
printf('%J\n',output);
