# r5 LAB validation — 2026-10-16

Hardware results were supplied by the operator executing commands on the test router.
These are observations from one LAB setup, not a general release certification.

## Tested setup

- Cudy WR3000U v1, OpenWrt 25.12.5, Linux 6.12.94, aarch64.
- Package upgraded from `1.0.0-r4` to `1.0.0-r5`.
- Tested package commit: `1cfe9a78a42d7c14be70cec9cea18017de750c7b`.
- Successful package build: https://github.com/djing1e/xtlsproVPN-for-OpenWRT/actions/runs/38871352873.
- One-arm IPv4 setup: Wi-Fi client and upstream gateway share `br-lan`; the client uses the LAB as its gateway.
- Watchdog monitors logical interface `lan`; flow offloading disabled.
- Custom DNS: Cloudflare DoH through proxy, IPv4, bootstrap Yandex DNS, fixed TTL 60.
- Baseline core: Xray 26.7.28. Upgrade candidate: official prerelease 26.10.10.

## Observed results

| Check | Result and evidence |
| --- | --- |
| Clean installation and initial core download | r4 APK and dependencies installed on clean OpenWrt; initial core installation from UI succeeded. |
| Subscription import and transports | Seven original nodes imported; an eighth XHTTP node was added and manually selected successfully before the later core tests. |
| Start / stop | Client tunnel works when enabled; ordinary internet and system DNS work when stopped. |
| Failed subscription download | Live core PID and configuration/catalogue hashes stayed unchanged. |
| Unreachable subscription candidate | Isolated HTTPS preflight rejected it; four configuration/catalogue hashes and live PID stayed unchanged. |
| Failure after subscription apply | Injected live validation failure caused rollback; original files, real HTTPS and DNS with TTL 60 passed. |
| Refresh with unchanged catalogue | Running core retained; no unnecessary restart. |
| DNS options | UI test did not apply settings; DoH apply succeeded; UDP and TCP queries through dnsmasq returned TTL 60. Stop/start retained working ordinary DNS and restored proxy DNS. |
| r5 reboot | Version r5, autostart, native interception, client tunnel and DNS UDP/TCP with TTL 60 verified. |
| Redirect protection | After boot: `all/send_redirects=0`, `br-lan/send_redirects=0`, `default/send_redirects=1`. Protection remained active when proxy was stopped. |
| Uplink disconnect / reconnect on r5 | Client internet returned immediately without Wi-Fi reconnect. Watchdog recorded an outage and recovery, returned healthy, and did not restart Xray. |
| Damaged local interception policy | Removal of owned rule 104 caused a client outage; watchdog restored it through recovery, restarted the core once, and returned healthy. This check was performed before the r5 upgrade. |
| Intentional proxy stop | Watchdog paused and did not revive the proxy. On r5, physical power removal and restoration while intentionally stopped kept enabled/autostart false, interception off, ordinary internet working and redirect protection active. |
| Subscription transaction power cut | Physical power was cut after the test candidate config rename and durable before-image, before service restart and commit. On boot, recovery logged restoration. Core/config/DNS/dhcp/catalogue/metadata checksums matched; HTTPS 204, DNS UDP/TCP TTL 60 and client tunnel passed. |
| Update after transaction recovery | Normal subscription sync succeeded; unchanged catalogue retained PID; real HTTPS and DNS TTL 60 passed. |
| Domain PROXY / DIRECT / BLOCK | SOCKS tests produced HTTP 200 for proxy/direct and a blocked connection for block. Access log confirmed `fx_node`, `direct`, and `blackhole_outbound`. Client confirmed example.com/example.net opened and example.org did not; native TPROXY traffic was observed. |
| User rule preservation | Before/after normalized rule objects matched across subscription sync; core retained and HTTPS healthy. Temporary test rules were subsequently removed and original access-log setting restored. |
| Core compatibility test | 26.10.10 accepted current config without replacing 26.7.28; baseline binary hash and PID unchanged. |
| Core upgrade | Cached candidate reused, 26.10.10 activated, prior binary preserved with matching SHA-256. HTTPS and DNS UDP/TCP TTL 60 passed. |
| Manual core rollback | Returned to 26.7.28 with exact original SHA-256; real HTTPS, DNS TTL 60 and client tunnel passed. |
| Automatic core rollback | Controlled post-switch health rejection caused the installed updater to restore 26.7.28 and report `rolled_back`. Original binary/config/DNS/dhcp/catalogue hashes, real HTTPS 204, DNS UDP/TCP TTL 60, native interception and client tunnel passed. |
| Schedule save | UI enabled both six-hour jobs, subscription at minute 0 and routing at minute 15. `crond` and its autostart became active without changing the Xray PID. |
| Actual cron execution | One-shot cron test ran normal subscription and routing update entry points sequentially, 10:29:00–10:29:18 UTC. Both succeeded, unchanged data retained PID 23785, temporary job removed, original crontab compared equal, schedule config checksum matched, HTTPS 204 and client routing worked. |

## Reproduction helpers

Scripts are restricted to the isolated LAB address; inspect before use elsewhere.
They contain no subscription credentials and do not require rebuilding the package.

- `scripts/test-subscription-rollback-lab.sh`
- `scripts/test-subscription-powercut-lab.sh` (`arm`, then `verify` after reboot)
- `scripts/test-core-auto-rollback-lab.sh`
- `scripts/test-schedule-cron-lab.sh` (`arm`, then `verify` after cron execution)

The core rollback test restores the pre-test backup file and does not change the
`keep_previous` preference. Test reports and rescue copies remain under `/root`.
The operator restored the original `keep_previous` preference after the manual test.

## Scope and remaining checks

- The physical transaction test covers a specific checkpoint, not arbitrary power loss during every filesystem write. The new journal protects subscription publication; core and APK updates do not use it.
- Manual core rollback and controlled health rejection were tested. The injected rejection is not evidence that 26.10.10 was actually incompatible; normal installation and manual rollback succeeded.
- Native domain rules were exercised. Separate IP/CIDR rule cases, DoT, alternate DNS providers, source-device exclusions and output-device binding have not been hardware-validated in this sequence.
- IPv6 interception is not implemented or validated by these IPv4 tests.
- Dedicated restricted-account permission checks and prolonged soak/load measurements remain outstanding. A single memory sample did not show temporary-file accumulation or memory pressure; it does not establish absence of leaks.
- Cron execution was accelerated using a separate one-shot job; the ordinary six-hour expressions were inspected and preserved, not observed through an entire six-hour cycle. Router time was UTC.
