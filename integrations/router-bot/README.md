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
and ssh.uc. The forced command is /etc/xtlspro-bot/ssh-entry. A later package or
sysupgrade integration will be needed before claiming firmware-upgrade persistence.

Protocol: exact SSH command strings, JSON schema 1 responses:

- xtlsbot-v1 status
- xtlsbot-v1 locations
- xtlsbot-v1 select cfgXXXXXX
- xtlsbot-v1 auto
- xtlsbot-v1 job UUID

The bridge never evaluates the requested command. Other commands, shells,
subsystems, extra whitespace/arguments and control characters are rejected.
Locations must be in the router's current imported catalogue. Selection uses
the existing controller's shared lock, live Xray API path and failure handling.
An accepted asynchronous job is not reported as a completed server switch.
Job polling must match the returned ID; replacement by a later UI operation
is reported explicitly. The bot must recheck client ownership on every callback.

Only a field whitelist is returned. Subscription metadata, URLs, addresses,
credentials, core config and logs are not exported. Display names come from
UCI aliases, with a generic fallback rather than the server endpoint.

First stage is a single test router. Administrative recovery commands and
the emergency VPS transport will be added separately after client selection
and identity checks are tested. No shared root shell key for client actions.
