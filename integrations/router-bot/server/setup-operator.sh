#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
test -s /etc/xtls-router-bot/config.json
work=$(mktemp -d /tmp/xtls-operator-install.XXXXXX)
trap 'rm -rf "$work"' EXIT
ref=bbe9da521d6b74d5876bfb088edd18fea4f0184a
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/integrations/router-bot/server"
for file in bot.py upgrade.py backup.py fleet.py connect.py operator_client.py operator_worker.py install-operator.py xtls-router-bot-operator.service xtls-router-bot-operator.path; do
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$file" -o "$work/$file"
done
cd "$work"
sha256sum -c - <<'SUMS'
86aeedcc3e3400936b420ca430f9a898d916a8571d5d8a6baa1eff83953e5656  bot.py
fce4f03e7ae08dae4638d23bf76757f19cb106d03d73151024857b75e50d5781  upgrade.py
94ddcb6bd7151be244eedf185de6d93ba83b2e7708022407d88a708024f5caa3  backup.py
0f3774a1b4ff5fa93377dec22adb73753f1cace8b3d2aa80c10b616ada7b0e0b  fleet.py
a2c433bc6f9f01b3e441d9e64050ff29c9ccaa5a4b008e326e9c27fe54db0f6f  connect.py
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
