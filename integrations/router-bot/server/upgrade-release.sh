#!/bin/sh
# Upgrade an existing operator VPS using only files from the verified release.
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
base=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$base"
sha256sum -c SHA256SUMS
systemctl is-active --quiet xtls-router-bot.service || {
    echo 'Нужен основной VPS с работающим ботом.'; exit 1
}
# These existing transactional installers preserve config, token and identities.
python3 ./server/install-operator.py
python3 ./server/install-connect.py
python3 /opt/xtls-router-bot/backup.py install
systemctl restart xtls-router-bot-backup.timer
python3 /opt/xtls-router-bot/backup.py create
systemctl is-active xtls-router-bot.service
systemctl list-timers --all --no-pager xtls-router-bot-backup.timer
echo 'Серверный комплект установлен. Парольная фраза и клиентские доступы сохранены.'
