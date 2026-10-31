#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
test -s /etc/xtls-router-bot/config.json
test -s /opt/xtls-router-bot/backup.py
work=$(mktemp -d /tmp/xtls-catalog-install.XXXXXX)
trap 'rm -rf "$work"' EXIT
ref=d3a552da9c7ce5cc0d8945017e4e7f580f514b2f
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in bot.py upgrade.py; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
33980abf649bfd71ee265d7163dba2673aa8620e0c13a67cfd53f045d014a645  bot.py
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
echo 'Готово. Откройте /start → Мои роутеры → Поиск. По 10 устройств на странице.'
