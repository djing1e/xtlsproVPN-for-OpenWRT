// Bounded RAM-only history: distinguish normal leastPing changes from restarts.
export function selection_event(previous,snapshot,now,reason) {
    let nodes=sort(map(filter(snapshot.nodes || [],n=>n.selected),n=>n.id));
    let current={pid:snapshot.core?.pid || null,nodes,mode:snapshot.mode || 'manual'};
    let changed=previous && (previous.pid!=current.pid || sprintf('%J',previous.nodes)!=sprintf('%J',nodes));
    let event=changed?{checked:now,type:previous.pid!=current.pid?'core_changed':'node_changed',
        previous_pid:previous.pid,pid:current.pid,previous_nodes:previous.nodes,nodes,
        mode:current.mode,watchdog:reason || null,proxy_ok:snapshot.health?.proxy_ok ?? null,
        health_checked:snapshot.health?.checked || null}:null;
    return {current,event};
};
