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
ref=1379dbc4b0017e63a9d0a37ff188b1a2fa38c720
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in backup.py install-daily-backup.py; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
5cd39e334a41dc609c4a4359926a408641e4d33fe4d5e27dd582c7304aebc90a  backup.py
8f2aebd3337ae614816c9f3b256c605730350ced1a9413eaadf056aefda97d1b  install-daily-backup.py
SUMS
python3 ./install-daily-backup.py
systemctl is-active xtls-router-bot.service
systemctl list-timers --all xtls-router-bot-backup.timer
journalctl -u xtls-router-bot-backup.service -n 12 --no-pager
