#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
test -s /etc/xtls-router-bot/config.json
work=$(mktemp -d /tmp/xtls-operator-install.XXXXXX)
trap 'rm -rf "$work"' EXIT
ref=8c26e88283cfb934f5127285a00aa163282c165d
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in bot.py upgrade.py backup.py fleet.py connect.py operator_client.py operator_worker.py install-operator.py xtls-router-bot-operator.service xtls-router-bot-operator.path; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
2957938d91608efa15d39914e6fa525d792e8261b8e535da8d53016a11660bbe  bot.py
9f634ba7307598a8e55738e8d94a544b2fe4a4985081962e78a2578b4fac3be7  upgrade.py
5cd39e334a41dc609c4a4359926a408641e4d33fe4d5e27dd582c7304aebc90a  backup.py
737b2aee94225a54b286bf015306ccde08bf7f4f3ea224f52390e8ca4432133c  fleet.py
5a0a6cd62925cbae12bec44b5e8bf1f84e2d254b82b08d8858f9a785de4ebeff  connect.py
32d959e21201d619f6dc7470bec577baa292380ec671135e43fd4951230ad70d  operator_client.py
fc3a639e7d61352b39eadda408dfc2e6781505e6012aac7cbe2f9faaaa7355c7  operator_worker.py
038e049fdaf85fd1adc4699610ed48dccba85338276c270c4d8b6070008a564a  install-operator.py
62b21b96415a39be7739630c51f428fe7a8701db14e7b1ef9c574a653890a769  xtls-router-bot-operator.service
be8f7ff32c5945a610c4a1a9255f1d62ed238ee4303dcf1b63d8be12e744937c  xtls-router-bot-operator.path
SUMS
python3 ./install-operator.py
systemctl is-active xtls-router-bot
systemctl is-active xtls-router-bot-operator.path
echo 'Откройте бота → Мои роутеры → Администрирование бота.'
