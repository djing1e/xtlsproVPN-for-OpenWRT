// Runtime-only selection. Health cadence is independent of Observatory cadence.
export function auto_decide(previous, input) {
    let s=previous || {}, now=input.now;
    let out={state:s,action:null,target:null,reason:'stable'};
    if (!input.enabled) { out.state={};out.reason='paused';return out; }
    const nodes=filter(input.nodes || [],n=>match(n.id || '',/^cfg[a-f0-9]{6}$/));
    const current=filter(nodes,n=>n.id==input.active)[0];
    if (s.pid!=input.pid || s.current!=input.active) {
        s={pid:input.pid,current:input.active,failures:input.health?.proxy_ok===false?1:0,health_checked:input.health?.checked,last_switch:now};out.state=s;
        if(current){out.action='pin';out.target=current.id;return out;}
    }
    if (!current && input.health?.proxy_ok===true) {out.reason='selection_unknown';return out;}
    if (current && s.pinned===false && input.health?.proxy_ok===true) {out.action='pin';out.target=current.id;return out;}
    // A cached health sample must never confirm a second failure or recovery.
    if (!input.health || input.health.checked==s.health_checked) return out;
    s.health_checked=input.health.checked;
    s.failures=input.health.proxy_ok===true?0:(s.failures || 0)+1;
    if (s.failures>=2 || !current) {
        s.better=null;s.streak=0;
        out.action='failover';out.reason='failed';
        const alternatives=filter(nodes,n=>n.id!=input.active);
        // Fresh successful observations are preferred, but stale/failed nodes
        // remain eligible for a new transport probe during an emergency.
        out.candidates=[...sort(filter(alternatives,n=>n.alive===true),(a,b)=>(a.rtt_ms || 0)-(b.rtt_ms || 0)),...filter(alternatives,n=>n.alive!==true)];
        return out;
    }
    if (s.failures || input.health.proxy_ok!==true) {s.better=null;s.streak=0;return out;}
    const better=sort(filter(nodes,n=>n.id!=input.active && n.alive===true && n.source=='observatory' &&
        current.source=='observatory' && current.alive===true && current.rtt_ms>0 && n.rtt_ms>0 &&
        current.rtt_ms-n.rtt_ms>=50 && n.rtt_ms<=current.rtt_ms*0.8),
        (a,b)=>a.rtt_ms-b.rtt_ms)[0];
    if (!better) {s.better=null;s.streak=0;return out;}
    if (s.better!=better.id) {s.better=better.id;s.streak=0;s.sample_current=0;s.sample_candidate=0;}
    if (current.checked>(s.sample_current || 0) && better.checked>(s.sample_candidate || 0)) {
        s.sample_current=current.checked;s.sample_candidate=better.checked;s.streak=(s.streak || 0)+1;
    }
    if (s.streak>=3 && now-s.last_switch>=300) {
        out.action='optimize';out.target=better.id;out.reason='better';
    }
    return out;
};

export function health_due(before,now,pid,interval) {
    return !before.probe_at || now-before.probe_at>=max(5,min(60,int(interval || 10))) || before.probe_pid!=pid;
};
