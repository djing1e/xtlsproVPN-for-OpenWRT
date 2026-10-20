#!/bin/sh
set -eu
umask 077

[ "$(id -u)" = 0 ] || { echo 'Запусти от root на VPS бота.'; exit 1; }
test -s /etc/xtls-router-bot/config.json
test -f /opt/xtls-router-bot/backup.py
for tool in python3 curl sha256sum ssh-keyscan; do command -v "$tool" >/dev/null; done

work=$(mktemp -d /tmp/xtls-connect-install.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
ref=79ba37a524660bfcf22e50480abcfe66f2dfb626
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in fleet.py connect.py backup.py xtls-router-add install-connect.py; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
0f3774a1b4ff5fa93377dec22adb73753f1cace8b3d2aa80c10b616ada7b0e0b  fleet.py
a2c433bc6f9f01b3e441d9e64050ff29c9ccaa5a4b008e326e9c27fe54db0f6f  connect.py
0b8f9599aaadcc23a906645b662f250ada0e1d342e2531994d76eff6577c47a6  backup.py
9d14575917d18b1f5a23a5552155cbd75c1686d6b9cdc43c4b20395963398246  xtls-router-add
0b40a71b2eb90bf1d74f8c9debc7c3d5ec16f5ab30c183e83d400ebd623834df  install-connect.py
SUMS

python3 /opt/xtls-router-bot/backup.py create
python3 "$work/install-connect.py"
python3 /opt/xtls-router-bot/backup.py create
echo 'Готово. Для подключения роутера выполни: xtls-router-add'
