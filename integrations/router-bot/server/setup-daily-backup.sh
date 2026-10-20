#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
test -s /etc/xtls-router-bot/config.json
systemctl is-active --quiet xtls-router-bot.service || {
    echo 'Ожидался основной VPS с работающим ботом.'
    exit 1
}
work=$(mktemp -d /tmp/xtls-daily-backup.XXXXXX)
trap 'rm -rf "$work"' EXIT
ref=db375e5cc01fc84daa72833e9394ef91a9a9fe26
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in backup.py install-daily-backup.py; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
78773957a9148a050ee60020eb0952dbb9aad5e23962daf7d605fd1d0b0dc96f  backup.py
8f2aebd3337ae614816c9f3b256c605730350ced1a9413eaadf056aefda97d1b  install-daily-backup.py
SUMS
python3 ./install-daily-backup.py
systemctl is-active xtls-router-bot.service
systemctl list-timers --all xtls-router-bot-backup.timer
journalctl -u xtls-router-bot-backup.service -n 12 --no-pager
