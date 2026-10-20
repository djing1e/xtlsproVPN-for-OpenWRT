# Router operations: rollout and acceptance

## Implemented in this iteration

- Subscription card: fixed brand label, numeric subscription number, refreshed and
  expiration timestamps, used/total/remaining counters and unlimited flag.
  The router bridge drops subscription URL, raw title, announce text, credentials
  and all other metadata before SSH output. Numeric ID is parsed only from an
  exact id: NUMBER announcement. Telegram never receives the subscription link.
- Customer display uses subscription numbers for assigned routers. Telegram
  numeric sender ID remains the access-control identity; router R-codes remain
  separate because multiple devices/users can share one subscription. A number
  in subscription metadata must never create a grant or become a login credential.
  Legacy internal U-codes remain readable for compatibility but aren't normal
  customer-facing labels. Enrollment requires the customer's Telegram ID.
- Read-only diagnostic snapshot: core, memory, observed interface, interception
  state and last cached HTTPS result. It does not run a second core or an active
  network test. No raw routes, LAN addresses, logs or configuration are exported.
- Per-router opt-in administrator monitoring: SSH availability about once a minute,
  alert after three consecutive failures and on recovery. HTTPS alerts require
  three distinct fresh failed snapshots; one stale cached error is not counted
  repeatedly. These probes never restart services or modify router configuration.
  Monitoring notices go only to the administrator and persist across restart.

Existing stable APK is unchanged. Update the optional router bridge first, then
update the bot. Existing SSH authorization/host pins and client grants remain.
The operator must verify real metadata and alert delivery on LAB before rollout.

## Next gate: emergency transport for LAB

HOME reverse SSH was tested previously. LAB needs its own reverse listener,
router identity and restricted server authorization before a bot can recover
NetBird when the normal transport is unavailable. Inspect LAB rescue status and
its public key; never copy its private key into chat or the bot server.

Use a unique loopback remote port per router. Give the bot a separate, constrained
SSH gateway identity allowing forwarding only to enrolled loopback listeners.
Do not reuse the administrator's VPS root key or the router's remote-forward-only
account for bot gateway access. Pin both gateway and target router host keys.
The same forced-command bridge must apply over the primary and rescue transports.

Acceptance: normal SSH fails, authorized rescue path reaches the same pinned LAB,
client location commands still cannot become admin commands, and a forged port
or router mapping cannot reach another device. Loss of both transports is reported
as unreachable; no bot can remotely repair loss of power or upstream internet.

## Administrative recovery

Expose separate fixed operations, never arbitrary shell strings. First actions:
restart Xray through the existing controller's recovery/health path; restart an
already registered NetBird service through the actual detected init wrapper.
Do not delete identity, reset registration, store a setup key, rewrite firewall,
DNS or network defaults as an automatic recovery action. Require an explicit
router-number confirmation and a correlated audit/job receipt. NetBird recovery
must be issued over the verified rescue transport. Apply per-router cooldown and
bounded attempts; monitoring alone is not permission to restart a router.

## Reboot

Administrator only, explicit target plus second confirmation, no queued duplicate
requests. Record reboot acceptance before dispatch. Verify emergency transport
and autostart first. Report separate phases: request accepted, device unreachable,
SSH restored, proxy health verified. Never report a reboot successful just because
the SSH command returned/disconnected. A deadline produces an unconfirmed result,
with the rescue connection instructions retained for the administrator.

## Updates

Use existing router package/Xray/NetBird update engines with their available-version,
architecture, checksum/signature, resource and preservation checks. Separate check,
review and install steps for each component. Show installed/candidate versions;
require confirmation of exact router and component. Preserve config, SSH/NetBird
identity and rescue enrollment. Serialize with selection, subscription sync and
recovery. No broad apk upgrade, automatic firmware upgrade or arbitrary binary URL.

Acceptance: check-only changes nothing; repeat clicks install at most once;
metadata/identity checks pass after install; interrupted transport is reconciled
with the correlated router job and subsequent health checks. Test LAB before any
client rollout. Firmware replacement needs its own backup/rollback procedure.

## Co-located bot and emergency endpoint

A bot VPS may also terminate router reverse tunnels. Each router uses a separate
restricted sshd account/key and unique loopback listener. In this topology the
bot needs no SSH gateway account: it connects directly to 127.0.0.1 on its own VPS
with the existing forced-command router identity. A failure of this VPS affects
both the bot and rescue access; the encrypted off-site backup remains necessary.

Optional router config: `"rescue":{"host":"127.0.0.1","port":22002}`.
Only loopback endpoints with unique nonprivileged ports are accepted. Use
`server/enroll_rescue.py --router ROUTER_ID --port PORT --host-key 'ssh-ed25519 KEY'`
after updating the application. Enrollment requires the rescue host key to equal
the already pinned primary router key, preserves file ownership, backs up config
and known_hosts, and rolls back both on startup failure. Rescue pins share the
existing known_hosts file and are included in encrypted backups/restores.

Reads retry through rescue only on SSH transport failure. Protocol errors and
router rejections are not retried. With rescue configured, mutations first probe
status to select a reachable channel, then dispatch exactly once. A lost mutation
response is unconfirmed and must never be automatically reissued through the
other channel. Job polling may switch channels because it is read-only. The
administrator's status card shows the channel used for its status snapshot.

## Fixed administrative jobs (LAB acceptance pending)

Upgrade the router first using router/upgrade-admin.sh with ssh.uc, admin.uc and
admin-worker, then update server/bot.py using the existing updater. No APK,
subscription, router identity or authorization-key replacement is required.

The administrator gets a Restoration menu with NetBird, proxy and reboot.
Recovery has an explicit target confirmation. Reboot needs an additional second
confirmation; confirmation tokens expire after two minutes and cancellation
invalidates them. All administrative callbacks and SSH dispatches recheck the
administrator role, even if a client somehow obtains a stored button token.
Local router locks serialize operations with selection; native NetBird and app
locks exclude concurrent UI/guard/package work. Both the bot's persistent audit
and the router enforce a five-minute shared cooldown. Per-boot UUID receipts
prevent a repeated administrative request from reexecuting after cooldown.

Each action requires an actual pinned rescue SSH connection before dispatch. If
the reserve is closed and NetBird is reachable, the explicit administrator request
opens the already configured rescue for 30 minutes. The bot never supplies a new
endpoint/key or changes enrollment. It sends the actual action only over rescue,
once. An ambiguous response produces an unconfirmed audit result, no replay.

NetBird restarts the enabled native init service or enabled netbird-wrapper;
it does not call login/up, use a setup key or modify registration/network settings.
Completion requires the correlated job, Management and Signal connected, plus a
successful separate SSH request via the primary NetBird address.

Proxy recovery calls the existing controller's asynchronous recover action with
its native validation and global lock, then verifies active HTTPS health. It
refuses an intentionally disabled transparent proxy. Reboot additionally requires
NetBird, Xray and rescue watcher autostart, and a running rescue watcher. A returned
reboot command is not success. The bot waits for a different valid boot UUID,
SSH restored, NetBird connected, and a successful proxy health snapshot from the
new boot. The deadline is five minutes; absence of proof is unconfirmed.

Acceptance order: verify admin-status and unsupported-command rejection through
rescue; run NetBird recovery and verify primary SSH; wait the five-minute cooldown,
run proxy recovery and check HTTPS/DNS; wait again and perform the twice-confirmed
reboot while local access is available. Verify the new boot, automatic reconnection,
retained identity/configuration and a client account's inability to see or invoke
these actions. Do not roll these new operations out to clients before acceptance.
Component update installation is not part of this change.
