# Subscription safety candidate — not approved for router installation

This branch combines the post-r4 TLS/progress fixes with a new staged subscription
transaction. It is an offline test candidate, not an APK release.

The recovery report shows a working seven-node deployment on Xray 26.9.9, an owned
priority-103 LAN rule after reboot, and NetBird-managed resolv.conf. A start job was
marked done despite proxy_ok=false. Later logs show no-route errors for DNS and all
seven node IPs. The pre-reboot failure logs are unavailable; a specific original
network outage cause is not established.

Implemented here:
- fetch catalogue into private RAM staging; keep live catalogue and core unchanged;
- validate generated config/firewall before live changes;
- run changed-node HTTPS, selected-balancer HTTPS and DNS tests in an isolated core;
- check current connection before switching;
- restore previous UCI/catalogue and restart old configuration if live validation fails;
- propagate proxy_ok=false as an action failure;
- clear desired state before stop; continue removing interception if local-rule cleanup fails;
- exclude only priority-103 exceptions to connected IPv4 networks from start conflicts;
- retain one bounded private failure record across reboot.

Tests cover 10 mocked transaction scenarios, false-health action status, and isolated
listener/changed-node selection. These do not establish real-router recovery.

Not yet completed: hardware tests with PPPoE/NetBird/TTL, process-kill/power-loss
recovery journal, and proof of direct DNS restoration after every stop failure.
Do not enable XHTTP on the router to test this branch yet. No installer is supplied.

Cold-install safety additions:
- bootstrap cleans partial staged binaries on failure and handled termination;
- verify minimal config and copied binary before publication; reject symlink targets;
- cold archive downloads allow up to 900 seconds; stalled downloads remain bounded;
- UI errors no longer claim an unvalidated candidate was cached;
- mocked bootstrap and UI failure tests cover download/digest failures, checksum,
  malformed/truncated archive, wrong version, config rejection, space and copy errors.
These tests guard network command calls; they do not prove router connectivity or
recovery after SIGKILL/power loss. No router installation was performed.
