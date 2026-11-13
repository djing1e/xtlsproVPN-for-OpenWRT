import { auto_decide } from './auto_policy.mjs';

// Caller holds the same action.lock as manual selection and subscription apply.
export function auto_run(s, g, previous, now, deps) {
    const enabled=g.fx_mode=='auto' && g.fx_watchdog_enabled=='1' && s.enabled && s.autostart &&
        s.interface.up && s.core.running && index(['pending','running'],s.job?.state)<0;
    if (!enabled) return {state:{},changed:false};
    const h=s.health;
    if (!h || h.proxy_pid!=s.core.pid || time()-h.checked<0 || time()-h.checked>30)
        return {state:previous || {},changed:false};
    const active=filter(s.nodes,n=>n.selected)[0]?.id;
    const r=auto_decide(previous,{enabled:true,now,pid:s.core.pid,active,nodes:s.nodes,health:h});
    const state=r.state;state.reason=r.reason;
    if (!r.action) return {state,changed:false};
    let target=r.target;
    if (r.action=='failover') {
        const candidates=r.candidates || [], count=length(candidates);
        let start=(state.cursor || 0) % max(1,count);
        for (let i=0;i<min(3,count);i++) {
            const node=candidates[(start+i)%count];
            state.cursor=(start+i+1)%count;
            if (node.probe_port>=11500 && node.probe_port<=65535 && deps.probe(node.probe_port).alive) {target=node.id;break;}
        }
        if (!target) {state.reason='no_candidate';return {state,changed:false};}
    } else if (r.action=='optimize') {
        const node=filter(s.nodes,n=>n.id==target)[0];
        if (!node || !(node.probe_port>=11500 && node.probe_port<=65535) || !deps.probe(node.probe_port).alive) {
            state.better=null;state.streak=0;state.reason='candidate_failed';return {state,changed:false};
        }
    }
    let old={},attempted=false;
    try {
        for (let tag in ['fx_main','fx_auto_pool']) old[tag]=deps.api('bi',['--json',tag])?.balancer?.override?.target || '';
        const desired='fx_node:'+target;
        for (let tag in ['fx_auto_pool','fx_main']) {
            attempted=true;deps.api('bo',['-b',tag,desired]);
            if (deps.api('bi',['--json',tag])?.balancer?.override?.target!=desired) die('API selection not confirmed');
        }
        if (r.action!='pin' && !deps.probe(11499).alive) die('Active route not confirmed');
        state.current=target;state.better=null;state.streak=0;state.sample=0;
        if (r.action!='pin') {state.last_switch=now;state.failures=0;state.reason=r.reason;}
        state.pinned=true;return {state,changed:attempted};
    } catch (error) {
        let restored=true;
        if (attempted) for (let tag in ['fx_main','fx_auto_pool']) {
            try {
                deps.api('bo',['-b',tag,...(old[tag]?[old[tag]]:['-r'])]);
                if ((deps.api('bi',['--json',tag])?.balancer?.override?.target || '')!=old[tag]) restored=false;
            } catch (ignored) {restored=false;}
        }
        state.pinned=false;state.better=null;state.streak=0;
        state.reason=restored?'api_failed':'api_unconfirmed';
        // Changed also covers an uncertain RPC. The monitor must probe again.
        return {state,changed:attempted};
    }
};
