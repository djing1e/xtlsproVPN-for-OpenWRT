# Direct Internet when the proxy is unavailable

The watchdog releases LAN interception after three fresh failed proxy HTTPS probes, even if the direct control probe also fails. Failed public DNS must not keep a dead tunnel active. A missing core or broken interception also enters direct mode after three observations. Cleanup is independent of core restart limits.

Direct mode is a runtime state, separate from user intent. Original dnsmasq forwarding is restored through the existing ownership journal; Xray firewall and policy rules are removed through the existing scoped cleanup. NetBird listener exclusions remain in place. Xray stays available on loopback for probes. The marker prevents service reloads from silently enabling interception again. Incomplete cleanup is retried.

The watchdog probes more frequently during an outage. Returning to proxy requires two fresh HTTPS successes, another HTTPS preflight, native DNS replies over UDP and TCP, successful LAN setup, and a post-activation HTTPS check. Failed validation keeps direct mode; a post-activation failure suspends interception again. Resume attempts are limited to one per minute. Core restarts remain limited to three per ten minutes and never enable interception during bypass.

Manual stop clears the runtime markers and desired/autostart state. Automatic recovery cannot override it. An explicit start may leave direct mode after its normal preflight checks. A disabled watchdog performs no automatic transitions.

Subscription replacement while in direct mode validates the candidate independently instead of requiring the expired old proxy to work. Successful replacement remains in direct mode until watchdog checks pass. Failed replacement restores the previous configuration and preserves direct mode.

Validation: failure policy, serialized worker and service cleanup tests; transaction tests cover renewal from a dead proxy and rollback while retaining direct mode. Before general rollout, use LAB to verify client DNS and direct HTTPS after loss of all proxy paths, renewal, recovery, and manual stop. These tests model loss of connectivity; a kernel hang or OOM event requires its own router logs.
