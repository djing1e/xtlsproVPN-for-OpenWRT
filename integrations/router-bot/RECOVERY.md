# Bot backup and recovery

The encrypted archive contains the bot application, SQLite state (including
stable IDs, grants and audit), Telegram token, bot SSH identity, pinned router
host keys and main systemd unit. It does not contain the encryption key, VPS OS,
NetBird identity, router firmware or VPS SSH/CrowdSec/firewall configuration.

## Keep copies outside the VPS

After installing backup.py, create a copy and inspect the timer:

```sh
clear
python3 /opt/xtls-router-bot/backup.py create
systemctl list-timers xtls-router-bot-backup.timer --no-pager
ls -lh /var/backups/xtls-router-bot/
```

Use MobaXterm SFTP to download the .tar.gpg file to a different computer/storage.
Download `/etc/xtls-router-bot/backup.key` separately and store it in a password
manager or separate protected location. Never send the key or Telegram token in
chat. Archive without key cannot be recovered. Do not delete the key on the VPS:
the timer needs it to create future copies. The timer keeps only 14 local copies;
regular offsite downloading/synchronization is still required.

To test a downloaded/reuploaded archive without changing the running bot:

```sh
clear
python3 /opt/xtls-router-bot/backup.py restore /root/ARCHIVE.tar.gpg \
    --key-file /etc/xtls-router-bot/backup.key \
    --output /root/xtls-restore-test
```

Choose an output directory that does not already exist. Restored plaintext
contains secrets; it is root-only and should be removed after verification.
The encrypted copy has already been decrypted and checked once by `create`.

## Restore on a different Debian VPS

1. Prepare Debian with Python 3, OpenSSH client and GnuPG. Preserve the new VPS's
   administrator SSH access. Stop the previous bot before starting another poller.
2. Install NetBird from its signed repository and register the new VPS with the
   existing management server. Permit it to reach the routers via the intended
   NetBird policy. Do not clone the old VPS's NetBird private identity.
3. Download the checked backup utility version used to create the copy. Upload
   the encrypted archive and its separate key to root-only files on the new VPS.
4. Run restore with `--apply` on a VPS with no installed bot application/config/
   state/unit. This creates the service account, restores files/ownership,
   reinstalls the backup timer and enables the bot, leaving the bot stopped.

```sh
clear
chmod 600 /root/backup.key /root/ARCHIVE.tar.gpg
python3 /root/backup.py restore /root/ARCHIVE.tar.gpg \
    --key-file /root/backup.key \
    --output /root/xtls-restored \
    --apply
```

After NetBird connectivity is ready and the previous poller is stopped:

```sh
clear
systemctl start xtls-router-bot
systemctl is-active xtls-router-bot
journalctl -u xtls-router-bot -n 15 --no-pager
```

Verify the administrator menu, stable router/user codes, assigned-client access
and manual/automatic selection. The restored SSH key is unchanged, so router
reauthorization is unnecessary as long as the router still trusts that key.
Remove the extra plaintext recovery directory after verification. Retain the
independently stored encrypted copy and recovery key. Do not run two bot pollers
against one Telegram token.
