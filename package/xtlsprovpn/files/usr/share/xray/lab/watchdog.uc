// Pure policy: a failed tunnel must not retain LAN/DNS interception.
// Runtime bypass preserves intent; an intentional stop never revives the proxy.
export function decide(old, input) {
    let s=old || {}, now=input.now;
    s.restarts=filter(s.restarts || [],t=>now-t<600 && now>=t);
    let result={state:s,action:null,reason:'healthy'};
    function outage() {
        if(s.outage_start==null){s.outage_start=now;s.outages=(s.outages || 0)+1;}
    }
    function recovered() {
        if(s.outage_start!=null){
            s.last_outage_seconds=max(0,now-s.outage_start);s.last_recovery=now;
            s.recoveries=(s.recoveries || 0)+1;s.outage_start=null;
        }
    }
    function bypass(reason) {outage();s.successes=0;result.action='bypass';result.reason=reason;return result;}
    function restart(reason) {
        if(length(s.restarts)>=3){result.reason='restart_limit';return result;}
        if(s.last_restart!=null && now-s.last_restart<90){result.reason='cooldown';return result;}
        push(s.restarts,now);s.last_restart=now;s.pending_interface=false;s.local_failures=0;
        result.action='restart';result.reason=reason;return result;
    }
    if(!input.enabled || !input.desired){
        s.failures=0;s.local_failures=0;s.successes=0;s.was_down=false;s.pending_interface=false;s.settle_until=0;
        s.wait_uplink=false;s.outage_start=null;s.signature=input.signature;
        result.reason='paused';return result;
    }
    // Mutations are serialized; do not fight a user action or subscription apply.
    if(input.busy){result.reason='operation_running';return result;}
    if(!input.interface_up){
        outage();s.was_down=true;s.signature=input.signature;s.successes=0;
        if(!input.bypass || input.interception)return bypass('interface_down');
        result.reason='interface_down';return result;
    }
    if(s.was_down || (s.signature && s.signature!=input.signature)){
        s.settle_until=now+input.settle;s.pending_interface=true;s.was_down=false;
    }
    s.signature=input.signature;
    if(s.settle_until && now<s.settle_until){result.reason='settling';return result;}
    if(input.bypass){
        // A partial cleanup is retried even if core restart limits were exhausted.
        if(input.interception || input.cleanup_needed)return bypass('direct_cleanup');
        if(s.pending_interface)return restart('interface_recovered');
        if(!input.core){
            s.local_failures=(s.local_failures || 0)+1;s.successes=0;
            if(s.local_failures>=3)return restart('local_integration_failed');
        } else {
            s.local_failures=0;
            if(input.probe_new){
                s.successes=input.proxy_ok?(s.successes || 0)+1:0;
                if(s.successes>=2 && (s.restore_at==null || now-s.restore_at>=60)){
                    s.restore_at=now;s.successes=0;result.action='restore';result.reason='proxy_recovered';return result;
                }
            }
        }
        result.reason='direct_mode';return result;
    }
    s.successes=0;
    if(s.pending_interface)return bypass('interface_recovered');
    if(!input.core || !input.interception){
        s.local_failures=(s.local_failures || 0)+1;
        if(s.local_failures>=3)return bypass('local_integration_failed');
    } else {
        s.local_failures=0;
        if(input.probe_new){
            if(input.proxy_ok){s.failures=0;s.wait_uplink=false;recovered();}
            else {
                outage();s.failures=(s.failures || 0)+1;s.wait_uplink=!input.direct_ok;
                // Direct DNS/HTTPS may also be blocked; this must not keep a dead tunnel active.
                if(s.failures>=3)return bypass('proxy_failed');
            }
        }
    }
    result.reason=s.failures || s.local_failures?'confirming_failure':'healthy';return result;
};
