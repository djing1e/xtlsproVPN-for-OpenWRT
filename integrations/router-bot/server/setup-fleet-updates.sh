#!/bin/sh
# Server-only update. Router mutations require a later explicit plan confirmation.
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
test -s /etc/xtls-router-bot/config.json
test -s /opt/xtls-router-bot/backup.py
work=$(mktemp -d /tmp/xtls-fleet-update-install.XXXXXX)
trap 'rm -rf "$work"' EXIT
ref=79d0e1febd471c761b0094ec614b149ead9026bd
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in bot.py upgrade.py;do
    curl -q -4 --noproxy '*' -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
c6eb50bed135eb980b4bf76d17058b526d7dff8d810d00bd7d08880d42ed6a51  bot.py
9f634ba7307598a8e55738e8d94a544b2fe4a4985081962e78a2578b4fac3be7  upgrade.py
SUMS
python3 - <<'CHECK'
import json,sqlite3,sys
from pathlib import Path
from upgrade import running_operations
config=json.loads(Path('/etc/xtls-router-bot/config.json').read_text())
if running_operations(config['database']):sys.exit('Дождитесь завершения операций роутеров и массовой очереди.')
with sqlite3.connect('file:'+config['database']+'?mode=ro',uri=True) as db:
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operator_jobs'").fetchone()
    if exists and db.execute("SELECT 1 FROM operator_jobs WHERE state='pending'").fetchone():
        sys.exit('Дождитесь завершения административной операции бота.')
CHECK
python3 /opt/xtls-router-bot/backup.py create
python3 ./upgrade.py
python3 /opt/xtls-router-bot/backup.py create
systemctl is-active xtls-router-bot
echo 'Массовое обновление добавлено. Откройте /start → Администрирование бота → Обновить все роутеры.'
echo 'Установки на роутерах не запускались. Для них требуется подтверждение плана в боте.'
