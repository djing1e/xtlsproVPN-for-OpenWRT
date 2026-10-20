#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
systemctl is-active --quiet xtls-router-bot.service || {
    echo 'Ожидался основной VPS с работающим ботом.'; exit 1
}
for unit in xtls-router-bot-backup.service xtls-router-bot-operator.service; do
    if systemctl is-active --quiet "$unit"; then
        echo 'Выполняется резервное копирование или административная операция. Дождись завершения.'
        exit 1
    fi
done
work=$(mktemp -d /tmp/xtls-backup-password.XXXXXX)
staged=''
trap 'rm -rf "$work"; [ -z "$staged" ] || rm -f "$staged"' EXIT
ref=1379dbc4b0017e63a9d0a37ff188b1a2fa38c720
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
curl -fLsS --connect-timeout 10 --max-time 60 "$base/backup.py" -o "$work/backup.py"
cd "$work"
sha256sum -c - <<'SUMS'
5cd39e334a41dc609c4a4359926a408641e4d33fe4d5e27dd582c7304aebc90a  backup.py
SUMS
python3 - <<'CHECK'
from pathlib import Path
compile(Path('backup.py').read_text(), 'backup.py', 'exec')
CHECK
previous=$(mktemp /root/backup-helper-before-passphrase.XXXXXX)
cp -p /opt/xtls-router-bot/backup.py "$previous"
staged=$(mktemp /opt/xtls-router-bot/.backup-passphrase.XXXXXX)
install -m 644 ./backup.py "$staged"
mv "$staged" /opt/xtls-router-bot/backup.py
staged=''
echo "Предыдущий скрипт: $previous"
echo 'Пароль вводится скрыто. Сохраните его вне VPS; не отправляйте в чат.'
python3 /opt/xtls-router-bot/backup.py password
systemctl reset-failed xtls-router-bot-backup.service
systemctl start xtls-router-bot-backup.service
systemctl is-active xtls-router-bot.service
journalctl -u xtls-router-bot-backup.service -n 8 --no-pager
