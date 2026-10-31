#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
systemctl is-active --quiet xtls-router-bot.service || { echo 'Ожидался основной VPS с работающим ботом.'; exit 1; }
for unit in xtls-router-bot-backup.service xtls-router-bot-operator.service; do
    if systemctl is-active --quiet "$unit"; then
        echo 'Дождитесь завершения резервного копирования или административной операции.'; exit 1
    fi
done
test -s /etc/xtls-router-bot/config.json
test -s /opt/xtls-router-bot/backup.py
work=$(mktemp -d /tmp/xtls-device-ui-install.XXXXXX)
trap 'rm -rf "$work"' EXIT
ref=2aa3f1802a5d459f495ffb09ecc8c50f4e14c2da
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in bot.py upgrade.py; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
5cf9e54476b3c3cf15a0f0599c662b0f92faae4212777e63dc2b4534b28ffa30  bot.py
9f634ba7307598a8e55738e8d94a544b2fe4a4985081962e78a2578b4fac3be7  upgrade.py
SUMS
# Do not stop the bot during a queued privileged operator operation.
python3 - <<'CHECK'
import json,sqlite3,sys
from pathlib import Path
config=json.loads(Path('/etc/xtls-router-bot/config.json').read_text())
with sqlite3.connect('file:'+config['database']+'?mode=ro',uri=True) as db:
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operator_jobs'").fetchone()
    if exists and db.execute("SELECT count(*) FROM operator_jobs WHERE state='pending'").fetchone()[0]:
        sys.exit('Дождитесь завершения административной операции в боте и повторите обновление.')
CHECK
python3 /opt/xtls-router-bot/backup.py create
python3 ./upgrade.py
python3 /opt/xtls-router-bot/backup.py create
systemctl is-active xtls-router-bot
echo 'Готово. /start → карточка роутера → Восстановление → Переименовать. Кнопка техподдержки доступна клиентам.'
