// Monotonic seconds only: wall-clock/NTP changes must not bypass restart limits.
export function guard_decide(previous, sample, now) {
    let s=previous || {};
    if (s.started==null || s.started>now) s={started:now,attempts:[]};
    s.attempts=filter(s.attempts || [], t => t<=now && now-t<3600);
    s.checked=sample.checked;s.uptime=now;s.action=null;
    function finish(reason,reset) {
        s.reason=reason;
        if (reset) {s.failure_since=null;s.failures=0;}
        return s;
    }
    if (!sample.enabled) return finish('paused',true);
    if (sample.healthy) return finish('healthy',true);
    if (sample.manual_down) return finish('manual_down',true);
    if (sample.auth_required) return finish('authentication_required',true);
    if (now-s.started<90) return finish('startup_grace',true);
    if (!sample.uplink) return finish('waiting_uplink',true);
    if (!sample.missing && !sample.unresponsive && !sample.management_reachable)
        return finish('management_unavailable',true);
    s.failure_since ??= now;s.failures=(s.failures || 0)+1;
    let delay=sample.missing?60:180;
    if (s.failures<3 || now-s.failure_since<delay) return finish('confirming_failure',false);
    if (length(s.attempts)>=3) return finish('rate_limited',false);
    let last=length(s.attempts)?s.attempts[length(s.attempts)-1]:null;
    let cooldown=length(s.attempts)==1?60:300;
    if (last!=null && now-last<cooldown) return finish('cooldown',false);
    // Count attempted commands, including commands that fail or time out.
    push(s.attempts,now);s.action=sample.missing?'start':'restart';
    s.failure_since=null;s.failures=0;s.settle_until=now+90;
    return finish('recovering',false);
};
