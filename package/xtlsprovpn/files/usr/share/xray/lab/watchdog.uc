// Pure state machine: monotonic seconds, separate interface and tunnel failures.
// No reboot, no restart while WAN is down, no revival after an intentional stop.
export function decide(old, input) {
    let s = old || {}, now = input.now;
    s.restarts = filter(s.restarts || [], t => now-t < 600 && now>=t);
    let result = {state:s,action:null,reason:'healthy'};
    if (!input.enabled || !input.desired) {
        s.failures=0; s.local_failures=0; s.was_down=false; s.pending_interface=false; s.settle_until=0;
        s.wait_uplink=false; s.outage_start=null; s.signature=input.signature;
        result.reason='paused'; return result;
    }
    function outage() {
        if (s.outage_start==null) {s.outage_start=now;s.outages=(s.outages || 0)+1;}
    }
    if (!input.interface_up) {
        outage();
        s.was_down=true; s.failures=0; s.local_failures=0; s.signature=input.signature;
        result.reason='interface_down'; return result;
    }
    if (s.was_down || (s.signature && s.signature != input.signature)) {
        s.settle_until=now+input.settle; s.pending_interface=true; s.was_down=false;
    }
    s.signature=input.signature;
    if (s.settle_until && now < s.settle_until) { result.reason='settling'; return result; }
    if (input.busy) { result.reason='operation_running'; return result; }
    let reason;
    if (input.core && input.interception) s.local_failures=0;
    if (s.pending_interface) reason='interface_recovered';
    else if (!input.core || !input.interception) {
        s.local_failures=(s.local_failures || 0)+1;
        if (s.local_failures>=3) reason='local_integration_failed';
    } else if (input.probe_new) {
        s.wait_uplink=false;
        if (input.proxy_ok) {
            s.failures=0;
            if (s.outage_start!=null) {
                s.last_outage_seconds=max(0,now-s.outage_start);s.last_recovery=now;
                s.recoveries=(s.recoveries || 0)+1;s.outage_start=null;
            }
        }
        else if (!input.direct_ok) {
            outage();s.failures=0; s.wait_uplink=true; result.reason='uplink_unavailable'; return result;
        } else {
            s.failures=(s.failures || 0)+1;
            if (s.failures>=3) reason='proxy_failed';
        }
    } else if (s.wait_uplink) {
        result.reason='uplink_unavailable'; return result;
    }
    if (!reason) { result.reason=s.failures || s.local_failures?'confirming_failure':'healthy'; return result; }
    if (length(s.restarts)>=3) { result.reason='restart_limit'; return result; }
    if (s.last_restart != null && now-s.last_restart < 90) { result.reason='cooldown'; return result; }
    push(s.restarts,now); s.last_restart=now; s.pending_interface=false; s.failures=0; s.local_failures=0;
    result.action='restart'; result.reason=reason; return result;
};
