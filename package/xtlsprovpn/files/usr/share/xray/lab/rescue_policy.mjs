export function rescue_decide(previous,sample,now) {
    let s=previous || {};
    if (s.uptime>now) s={};
    s.uptime=now;s.action=null;
    if (!sample.enabled) {s.reason='disabled';if(sample.running)s.action='stop';return s;}
    if (s.pause_until>now) {s.reason='paused';if(sample.running)s.action='stop';return s;}
    let manual=s.manual_until>now;
    if (sample.healthy) {s.outage_since=null;s.healthy_since ??=now;}
    else {s.healthy_since=null;s.outage_since ??=now;}
    if(!sample.netbird_enabled || sample.manual_down)s.outage_since=null;
    let wanted=manual || sample.netbird_enabled && !sample.manual_down &&
        (sample.healthy ? sample.running && now-s.healthy_since<600 : now-s.outage_since>=300);
    if (!wanted) {
        s.reason=sample.running?'closing':sample.healthy?'standby':'waiting';
        if(sample.running)s.action='stop';
        return s;
    }
    if (sample.running) {
        s.reason=manual?'manual':'active';
        if (sample.established) {
            s.established_since ??=now;
            if(now-s.established_since>=60)s.failures=0;
        } else {
            s.established_since=null;
            if(s.launched!=null && now-s.launched>=90){s.action='stop';s.reason='connect_timeout';}
        }
        return s;
    }
    s.established_since=null;
    if(s.retry_at>now){s.reason='retry_wait';return s;}
    s.failures=(s.failures || 0)+1;
    let delays=[30,60,120,300];
    s.retry_at=now+delays[min(s.failures-1,3)];s.launched=now;
    s.reason='starting';s.action='start';return s;
};
