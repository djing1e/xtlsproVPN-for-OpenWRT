#!/bin/sh
# Targeted bridge update; leaves APK, settings, Xray and NetBird untouched.
set -eu
umask 077
[ "$(id -u)" = 0 ]
dest=/etc/xtlspro-bot
for name in updates.uc update-worker; do
    [ -f "$dest/$name" ] && [ ! -L "$dest/$name" ]
done
work=$(mktemp -d /tmp/xtls-bot-confirm.XXXXXX)
backup=
installing=0
cleanup() {
    rc=$?; trap - EXIT
    if [ "$rc" != 0 ] && [ "$installing" = 1 ]; then
        cp -p "$backup/updates.uc" "$dest/updates.uc"
        cp -p "$backup/update-worker" "$dest/update-worker"
        echo 'Предыдущие обработчики восстановлены.'
    fi
    rm -rf "$work"
    exit "$rc"
}
trap cleanup EXIT
base=https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/13510222cb68349592382a3fb9a51786b451b93d/integrations/router-bot/router
for name in updates.uc update-worker; do
    curl -q -4 --noproxy '*' -fL --connect-timeout 10 --max-time 60 "$base/$name" -o "$work/$name"
done
(cd "$work"; sha256sum -c - <<'SUMS'
40a5a0d6be2514b7a18e131bc7258cfed345cb8675ecb92630d4da3646ebe134  updates.uc
f6196953e91c5d901aa0cdfbe982a7bf2a88487483888a4dfa901032349bbb24  update-worker
SUMS
)
ucode -c -o "$work/updates.ucb" "$work/updates.uc"
sh -n "$work/update-worker"
mkdir -p /var/run/xtlspro-bot-admin /var/run/xray-lab-control
exec 7>/var/run/xtlspro-bot-admin/action.lock
flock -n 7 || { echo 'Задание бота выполняется. Повторите после завершения.'; exit 1; }
exec 8>/var/run/xray-lab-control/action.lock
flock -n 8 || { echo 'Операция приложения выполняется. Повторите после завершения.'; exit 1; }
backup=$(mktemp -d /root/xtls-before-bot-confirm.XXXXXX)
for name in updates.uc update-worker; do cp -p "$dest/$name" "$backup/$name"; done
installing=1
for name in updates.uc update-worker; do
    cp "$work/$name" "$dest/$name.new"
    chmod 600 "$dest/$name.new"
    [ "$name" != update-worker ] || chmod 700 "$dest/$name.new"
    mv "$dest/$name.new" "$dest/$name"
done
installing=0
echo "Обработчик подтверждения обновлений исправлен. Резервная копия: $backup"
echo 'Службы и настройки не изменены. Повторная установка APK не требуется.'
