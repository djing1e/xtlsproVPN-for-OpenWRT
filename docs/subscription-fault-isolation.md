# Subscription transport and node failure isolation

Subscription downloads use a direct connection with HTTPS verification. They ignore proxy environment variables and do not fall back through a subscription node. DNS resolution and reachability of the subscription server remain requirements for a fresh download. A download or parsing failure preserves the installed catalogue and running configuration.

Network failure of a new or changed node does not veto every other usable route. Candidate structure, Xray validation, firewall syntax, resource guards and transaction recovery remain mandatory. The update still records failed node probes in its operation log; the normal per-node checks report node availability after activation.

For low-memory sequential checks, optional changed-node probes may fail. In automatic mode activation candidates are ordered by fresh live observations, and checked one at a time until a single candidate passes both HTTPS and DNS. Manual mode tests only the explicitly selected node for activation; it never silently chooses another country. If no permitted candidate passes, the previous catalogue and configuration remain active.

For the full independent check, failed changed-node probes are informational, while the actual main balancer route and DNS must pass. The main test listener is explicitly routed to fx_main and bypasses user DIRECT rules.

Startup and watchdog health checks use a dedicated loopback SOCKS listener on 11499, routed directly to the active main balancer. A successful direct request through a generic policy-controlled SOCKS listener is not accepted as proof that the proxy route works. LAN interception is activated only after the main-route HTTPS and resolver checks pass.

Regression tests simulate a bad extra node, a failing first automatic candidate, a first candidate with broken DNS, all automatic candidates failing, and a selected manual node failing. Existing transaction, rollback, memory and validation tests remain enabled.

This change does not claim that a bad node explains every symptom of the HOME incident: the dead NetBird resolver and inaccessible public UDP DNS servers were independently observed. DNS recovery while the proxy is stopped is a separate known issue. These changes are prepared for 1.4.3-r1. Publishing the release does not install it on routers.
