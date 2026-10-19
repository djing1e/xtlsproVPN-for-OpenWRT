#!/usr/bin/ucode
import * as fs from 'fs';
import { cursor } from 'uci';
import { guard_decide } from '/usr/share/xray/lab/netbird_guard_policy.mjs';

const RUN='/var/run/xtlspro-netbird';
const BIN='/usr/bin/netbird';
const SERVICE='/etc/init.d/netbird';
function quote(v) {return "'"+replace(''+v,/'/g,"'\\''")+"'";}
function capture(args,seconds) {
    let p=fs.popen(join(' ',map(['timeout','-k','2',''+seconds,...args],quote))+' 2>/dev/null','r');
    if (!p) return {ok:false,text:''};
    let text=p.read('all') || '';return {ok:p.close()==0,text};
}
function parse(text) {try {return json(text);}catch(e){return null;}}
function write(s) {
    let f=fs.open(RUN+'/guard.json.new','w',0600);
    if (!f) die('Cannot save NetBird guard state');
    let ok=f.write(sprintf('%J',s));f.close();
    if (!ok || !fs.rename(RUN+'/guard.json.new',RUN+'/guard.json')) die('Cannot save NetBird guard state');
}
function https(url,device) {
    // Bind to the physical uplink; no proxy environment and no TLS bypass.
    let r=capture(['curl','-4','--silent','--noproxy','*','--interface',device,
        '--connect-timeout','3','--max-time','5','--output','/dev/null',
        '--write-out','%{http_code}',url],6);
    return r.ok && !!match(r.text,/^[234][0-9][0-9]$/);
}
let now=int(split(fs.readfile('/proc/uptime') || '0',' ')[0]);
let s=parse(fs.readfile(RUN+'/guard.json') || '') || {};
let previous_reason=s.reason;
let cfg=cursor().get_all('xray_lab_netbird','main') || {};
let sample={checked:time(),enabled:cfg.enabled=='1' && capture([SERVICE,'enabled'],2).ok};
if (sample.enabled) {
    sample.missing=!capture(['pidof','netbird'],2).ok;
    if (!sample.missing) {
        let r=capture([BIN,'status','--json'],4), d=r.ok?parse(r.text):null;
        sample.unresponsive=type(d?.management)!='object';
        sample.healthy=d?.management?.connected===true && !!d?.netbirdIp && d?.signal?.connected!==false;
        sample.manual_down=d?.daemonStatus=='Idle';
        sample.auth_required=index(['NeedsLogin','LoginFailed','SessionExpired'],d?.daemonStatus)>=0;
    }
    if (!sample.healthy && !sample.manual_down && !sample.auth_required &&
        s.started!=null && now>=s.started+90 && !(s.settle_until>now)) {
        let routes=capture(['ip','-4','route','show','table','main','default'],2);
        let device=match(routes.text,/[[:space:]]dev[[:space:]]+([A-Za-z0-9_.:-]+)/)?.[1];
        if (device) {
            let url=cfg.management_url || '';
            // Use only the administrator's saved HTTPS endpoint; never values from status output.
            if (match(url,/^https:\/\/[A-Za-z0-9][A-Za-z0-9.:-]*(\/[A-Za-z0-9._~\/%-]*)?$/))
                sample.management_reachable=https(url,device);
        }
        // A reachable management endpoint is itself proof of uplink. Do not
        // depend on public probe hosts when they are blocked by the provider.
        sample.uplink=!!device && (sample.management_reachable ||
            https('https://1.1.1.1/cdn-cgi/trace',device) || https('https://1.0.0.1/cdn-cgi/trace',device));
    }
}
// Recovery has its own settle period, without consuming another failure sample.
if (sample.enabled && !sample.healthy && s.settle_until>now) {
    s.checked=sample.checked;s.uptime=now;s.reason='settling';s.action=null;write(s);exit(0);
}
let next=guard_decide(s,sample,now);
if (next.action) {
    // Persist the budget before running a command; a killed worker cannot erase it.
    write(next);
    capture(['logger','-t','xray-netbird-guard','NetBird recovery: '+next.action],2);
    next.command_ok=capture([SERVICE,next.action],20).ok;
    next.recovery_attempts=(next.recovery_attempts || 0)+1;
} else if (next.reason!=previous_reason) {
    capture(['logger','-t','xray-netbird-guard','NetBird state: '+next.reason],2);
}
write(next);
