# Router bot bridge — development

Opt-in SSH bridge for the separate administration bot. It is not bundled in the
stable router APK yet and does not install a Telegram client on routers.

The bot has its own SSH identity. Authorize it only with a forced command and
no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty. Keep current
administrator keys and Dropbear configuration unchanged. Pin the verified
router host key on the bot server.

Password-only test routers without authorized_keys are supported: the installer
creates the file with mode 0600 and records its previous absence in the backup.
Existing keys and valid symlinks are preserved; directories/dangling symlinks
are rejected. Password authentication is not changed by the installer.

Root must have a non-empty password before enrollment. On LAB, SSH accepted
the initial connection using an empty root password (SSH none authentication),
so key restrictions were not applied. That prototype key was revoked before
further testing. The installer now fails before authorization when the root
shadow record is empty or missing. Set a password interactively; never send
it to the bot or include it in source. The SSH client must use publickey-only
settings, but those alone are not a substitute for refusing empty-password
accounts. Real SSH positive/negative tests remain required before enrollment.

Files live in /etc/xtlspro-bot (root-owned, not writable by the bot): ssh-entry
and ssh.uc, plus admin.uc/admin-worker and updates.uc/update-worker for fixed administrative jobs. The forced command is /etc/xtlspro-bot/ssh-entry. A later package or
sysupgrade integration will be needed before claiming firmware-upgrade persistence.

Protocol: exact SSH command strings, JSON schema 1 responses:

- xtlsbot-v1 status
- xtlsbot-v1 locations
- xtlsbot-v1 select cfgXXXXXX
- xtlsbot-v1 auto
- xtlsbot-v1 job UUID
- xtlsbot-v1 diagnostics
- xtlsbot-v1 admin-status
- xtlsbot-v1 admin-open-rescue
- xtlsbot-v1 admin netbird|proxy|reboot UUID
- xtlsbot-v1 updates
- xtlsbot-v1 update-check app|xray|netbird UUID
- xtlsbot-v1 update-install app|xray|netbird UUID PLAN_UUID

The bridge never evaluates the requested command. Other commands, shells,
subsystems, extra whitespace/arguments and control characters are rejected.
Locations must be in the router's current imported catalogue. Selection uses
the existing controller's shared lock, live Xray API path and failure handling.
An accepted asynchronous job is not reported as a completed server switch.
Job polling must match the returned ID; replacement by a later UI operation
is reported explicitly. The bot must recheck client ownership on every callback.

Only a field whitelist is returned. Raw subscription metadata, URLs, addresses,
credentials, core config and logs are not exported. Display names come from
UCI aliases, with a generic fallback rather than the server endpoint.

Deployment remains a single-router LAB pilot. Administrative recovery requires
the separately enrolled, pinned emergency transport. Client actions never grant
a root shell or administrative capabilities.


## Telegram pilot with client access

`server/bot.py` uses Python 3.13's standard library, Telegram HTTPS long polling,
SQLite and OpenSSH. No pip dependencies or inbound web listener. The systemd
service runs as the existing `xtlsrouterbot` user. Application/config files are
root-owned; the SSH directory is read-only in the service sandbox. The token is
entered via getpass, verified against @xtlsproroutbot, stored root-only and passed
using systemd LoadCredential. It is never an argument or a logged HTTP URL.
Existing webhooks are refused, not silently removed.

The initial installation is a LAB pilot. The configured administrator sees all
configured routers. Clients receive explicit per-router grants in SQLite and
see only their assigned routers, in private chats. SSH uses the previously
tested bot key and pinned router host keys. The installer preserves the SSH identity,
backs up previous application/config/unit, and refuses differing existing config.
Fixed administrative operations are available after the router helper upgrade;
see OPERATIONS.md for their checks and LAB acceptance sequence.

Menu: router status, locations, automatic selection. Health is labelled as the
last cached check; applying a selection is not itself a fresh health probe.
Opaque 15-minute button tokens bind user/router/action on the server; mutating
buttons are single-use. Access is rechecked for every callback and before SSH.
Only one mutation per router is allowed. Replies report success only after a
matching router job reaches done; timeout, replacement and failure are explicit.

SQLite stores update offset, button receipts and mutation audit state (no raw
router replies, secrets or Telegram message bodies). Offset is saved before
handling: after a crash a request may need to be repeated, but a mutation is not
automatically replayed. Pending local audit rows become interrupted on restart;
router work may still finish, so check current status before repeating. No claim
of exactly-once delivery or rollback across Telegram, SSH and SQLite.

Run `server/install.py` as root from an interactive terminal, alongside bot.py
and xtls-router-bot.service. Existing account, SSH key, known_hosts and tested
router bridge are prerequisites. Install only after verifying the download
checksums. Setup does not send Telegram messages: the user initiates /start.

Verified on LAB before Telegram deployment:
- Nonempty root password established; limited bot key restored.
- Remote status/locations succeeded; arbitrary id rejected with exit 1.
- Remote Switzerland and auto jobs completed; UI observed both changes.
- Xray PID stayed 4392; subsequent proxy health HTTP 204, 218 ms.

Local automated tests cover bridge/installer boundaries and Telegram access,
callback ownership/expiry/replay, per-router locking, matching completion,
failed/replaced/timed-out jobs, SSH policy and error redaction. Live Telegram
button tests remain a deployment acceptance step.


## Client enrollment and revocation

An unbound user starts the bot and receives only their own numeric Telegram ID.
The administrator uses `/bind ROUTER_ID TELEGRAM_ID`; the bot shows the exact
router/name and numeric ID and requires a single-use confirmation. `/unbind`
uses the same confirmation flow. `/access ROUTER_ID` (or the administrator-only
router access button) lists grants and offers revocation buttons. `/help` lists
configured router IDs for the administrator. Access changes enqueue a customer notification, including an Open router button
after approval. Telegram delivery failures are retained/reported; clients who
never opened or blocked the bot must open/unblock it first.

Clients can view status/locations and select a location or auto on their assigned
routers only. They cannot list grants, issue/revoke grants or use administrator
buttons. Unknown/removed routers and group chats are refused. Tokens are bound
to the sender ID and current grant generation. Revocation deletes old buttons;
regrant creates a different generation so queued workers and old receipts cannot
regain access. Permission is checked before every SSH dispatch and router-data
response. Revocation is serialized with dispatch and takes effect once confirmed;
an already accepted router job may complete and is not cancelled retroactively.

Access changes are recorded in a local SQLite audit with actor, target ID,
router, operation and time. Roles are derived from configured administrator ID
plus explicit grants; granting a router never grants an administrator role.
Grant data and generations persist through restart. Schema upgrades are additive
and preserve the previous pilot's administrator buttons and operation receipts.

Update an existing VPS via `server/upgrade.py` alongside the checked bot.py.
It does not ask for or replace the token, config, SSH key or known_hosts. It
refuses active router operations, briefly stops only the bot service, creates a
SQLite backup, tests migration on a copy and atomically replaces the application.
On failure it restores application code without rewinding live grant changes.
Router services and the stable APK are not touched. Test with a second Telegram
account: unbound start, grant, own-router switch, revoke, old-button refusal,
regrant and restart persistence. First live administrator selection through the
Telegram interface was confirmed on LAB before this client-access extension.


## Button navigation

Administrator flow: router → Client access → Add client → enter numeric Telegram
ID → confirm. Client access lists revoke buttons; each revoke still requires
confirmation. Navigation provides My routers, Status, My ID and Help buttons.
Existing slash commands remain available for support but are not required for
normal grant/revoke operations. New users still use Telegram's initial Start.

The input dialog is bound to the administrator and selected router, persists in
SQLite and expires after ten minutes. Invalid input cannot grant access; it keeps
the dialog open for correction. Cancel or any other valid callback closes the
input dialog; cancelling confirmation invalidates pending access confirmations
for that router. Clients cannot start this dialog even through forged callbacks.
Only the final single-use confirmation changes grants. Existing grants, audit,
SSH policy and job semantics are unchanged. Client enrollment/revocation was
reported working by the operator before this button-navigation refinement.


## Notifications, IDs and repeated clicks

Router codes R-000001 and user codes U-000001 are immutable local registry IDs,
independent of model/name. They survive database backup/restore. Existing config
router keys remain permanent routing identities; never recycle a key for a
different physical router. SSH host-key pinning remains the actual endpoint
verification. Display codes never authorize a user. User profiles are captured
from private-chat sender data; confirmations include display code/name and exact
Telegram numeric ID. Enrollment input accepts U-codes or Telegram numeric IDs.

Grant/revoke changes atomically enqueue notifications in SQLite. Approval sends
an Open router button. Undeliverable messages (chat not started/blocked) notify
the administrator without undoing the grant. Transient errors retry. Superseded
access events are not delivered as current grants. Outbox delivery is at least
once: an ambiguous Telegram timeout may produce a duplicate notice on retry.

All callback receipts are single-use, including read buttons. Used/expired
receipts get a callback toast rather than a new chat message or SSH request.
Router reads execute in a bounded worker pool with one pending read per user;
repeat clicks while that read is pending are acknowledged as processing. Existing
per-router mutation locks and generation checks remain. A deliberate new menu
provides fresh buttons after each completed read; old buttons cannot replay work.

## Portable backups

`server/backup.py install` creates a random root-only backup.key outside archives,
installs a daily systemd timer (03:15 server time, up to 15 minute jitter), and
keeps the latest 14 verified encrypted archives under /var/backups/xtls-router-bot.
`create` takes a consistent online SQLite backup, packages app/config/token/SSH
identity/pinned hosts/unit, encrypts with GnuPG AES256, decrypts and verifies the
archive before publishing or rotating copies. Plaintext staging uses /run.
The archive and separately saved backup.key are both required for restoration.

Download archives regularly to a separate machine/storage and keep the key
separately. Local automatic backups alone do not survive VPS loss. This version
does not upload copies to Telegram or an external cloud. Operator must arrange
offsite copies before treating recovery as complete. NetBird registration, VPS
OS, firewall and CrowdSec are outside this bot backup. See RECOVERY.md for the
new-VPS process. A restored bot stays stopped until NetBird is ready and the old
poller is stopped. Existing bot installations are never overwritten by restore.


## Subscription display and operational status

The optional router bridge now adds a strictly filtered subscription card to
status and a read-only diagnostics snapshot. The bot shows the subscription's
numeric customer number, timestamps and traffic without receiving the URL,
raw title/announcement or other metadata. Telegram sender ID remains the access
identity; the subscription number is a display/business identifier, not a grant.

Administrator monitoring can be enabled per router from its status card. It
checks SSH availability and distinct fresh cached HTTPS probe results. Three
consecutive failures produce a notice; recovery produces one recovery notice.
Monitoring is off until explicitly enabled, never restarts services and does not
replace the router's existing guard. New capabilities and the remaining gates
for administrative recovery, reboot and future updates are specified in
OPERATIONS.md. Recovery/reboot passed live LAB acceptance. Component updates have automated
coverage and require live catalogue and installation acceptance before rollout.

## Fleet onboarding and packaged router helpers

APK 1.4.0-r1 includes a public router helper bundle without granting access on
installation. `xray-lab-bot prepare PROFILE.json` creates a persistent device UUID
and a public enrollment code. The root-only `server/fleet.py` verifies identity,
allocates a restricted per-router relay account/port and checks both SSH paths
before committing the registry. Existing LAB adoption preserves its router key,
R-code and client grants. See [ONBOARDING.md](ONBOARDING.md) for operator commands,
rollback, archive compatibility and VPS migration limits.

## LAB acceptance for 1.4.0-r1

The package, enrollment, idempotent adoption, primary/rescue return, reboot and
in-place helper refresh have been exercised on LAB. See
[the dated validation record](../../docs/router-bot-validation-2026-10-20.md)
for evidence, VPS-side fixes and the precise limits of physical acceptance.
