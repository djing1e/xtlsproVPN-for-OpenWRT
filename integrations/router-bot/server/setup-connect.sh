#!/bin/sh
set -eu
umask 077

[ "$(id -u)" = 0 ] || { echo 'Запусти от root на VPS бота.'; exit 1; }
test -s /etc/xtls-router-bot/config.json
test -f /opt/xtls-router-bot/backup.py
for tool in python3 curl sha256sum ssh-keyscan; do command -v "$tool" >/dev/null; done

work=$(mktemp -d /tmp/xtls-connect-install.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
ref=c6af8a659089f7cf47ded5a2094e5cea706989eb
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in fleet.py connect.py backup.py xtls-router-add install-connect.py; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
a43ed4970258f390d6c48c547d2e2fcabecf0dd8d47ebbbb2a7c987a4b6777c1  fleet.py
1903876023a2ff6371f7d496cd5703273688e2344a63a3a4524e647ef5089e23  connect.py
86c60d2028d337d16bf586deeb7d0273dc4aa897e06f41cbe08609399519677d  backup.py
9d14575917d18b1f5a23a5552155cbd75c1686d6b9cdc43c4b20395963398246  xtls-router-add
0b40a71b2eb90bf1d74f8c9debc7c3d5ec16f5ab30c183e83d400ebd623834df  install-connect.py
SUMS

python3 /opt/xtls-router-bot/backup.py create
python3 "$work/install-connect.py"
python3 /opt/xtls-router-bot/backup.py create
echo 'Готово. Для подключения роутера выполни: xtls-router-add'
