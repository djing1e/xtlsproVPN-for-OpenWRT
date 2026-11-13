# Stable Auto and independent health checks

The active proxy path is checked on its own timer (`fx_health_interval`, default
10 seconds, configurable 5–60). `fx_probe_interval` remains the Observatory timer
for background measurements of all locations (default 60 seconds, 30–3600).
Existing custom background intervals are preserved.

The monitor pins the initially selected node through Xray's Routing API. A lower
RTT alone no longer changes the route. A candidate must improve latency by both
20% and 50 ms in three distinct paired Observatory samples. The last change must
be at least five minutes ago. Cached health/latency samples do not count again.
The candidate and the active proxy path are verified over HTTPS before accepting
a change. Existing connections keep their outbound handlers.

Two distinct failed health checks trigger emergency selection regardless of the
five-minute hold. Candidates with fresh successful measurements are tried first;
stale or failed measurements do not prevent a fresh emergency transport test.
At most three candidates are tested per cycle, rotating through the remainder.
If no candidate passes, the existing fail-open policy releases LAN/DNS interception
after the second failed check. Recovery requires the existing HTTPS and native
UDP/TCP DNS gates. Manual mode never changes its selected node automatically.

These are scheduling intervals, not a zero-outage guarantee: actual detection
also includes bounded network requests, API calls, and the monitor's five-second
poll. Monitor HTTPS requests and candidate checks have three-second deadlines.
The fast monitor does not wait for a direct DNS/HTTPS probe before fail-open.

The selector takes the same action lock as manual changes and subscription
updates, then rechecks mode, desired state, process identity and sample freshness.
Uncertain API writes are rolled back and followed by another active health check.
It does not restart Xray, rebuild DNS/firewall, or write selections to flash.
State is kept in `/var/run/xray-lab-control/auto-selection.json` and resets when
Xray or the selected node changes. API recovery and fail-open remain independent.
Disabling watchdog stops automatic route changes and fail-open. The last runtime
pin remains until an explicit selection or process restart.
