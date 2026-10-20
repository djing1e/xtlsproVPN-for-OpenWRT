#!/bin/sh
# Public bootstrap for an already configured xtlsproVPN 1.4 router.
set -eu
umask 077
fail() { echo "Подключение бота: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || fail 'Запусти от root на роутере.'
[ "$#" = 1 ] || fail 'Нужен публичный код профиля из мастера VPS.'
[ -x /usr/bin/xray-lab-bot ] || fail 'Сначала обнови xtlsproVPN до 1.4.0 или новее.'
for tool in ucode base64 jsonfilter dropbearkey; do command -v "$tool" >/dev/null || fail "Не найдена команда $tool"; done
case "$1" in xtls-profile-v1:*) encoded=${1#xtls-profile-v1:} ;; *) fail 'Неверный формат профиля.' ;; esac
[ "${#encoded}" -le 4096 ] || fail 'Превышен размер профиля.'
work=$(mktemp -d /tmp/xtls-bot-join.XXXXXX)
trap 'rm -rf "$work"' EXIT
printf '%s' "$encoded" | base64 -d > "$work/profile.json" || fail 'Профиль повреждён.'
# Native preparation validates the profile and preserves an existing UUID/key.
if ! /usr/bin/xray-lab-bot prepare "$work/profile.json" > "$work/prepare.log" 2>&1; then
    cat "$work/prepare.log"
    fail 'Подготовка не завершена; регистрация на VPS не выполнялась.'
fi
# Update only the restricted public bridge; identity, keys and routing are kept.
curl -fLsS --connect-timeout 10 --max-time 60 \
    https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/a8ff7ee08b46eefd6b053e9bd267669961ee832c/integrations/router-bot/router/upgrade-hwid.sh \
    -o "$work/upgrade-hwid.sh"
printf '%s  %s\n' 049cb558368566d9782ebd4aad9d3f280d32d456a6aac780a4736eacb45661e7 "$work/upgrade-hwid.sh" | sha256sum -c -
sh "$work/upgrade-hwid.sh"
passport=/root/xtls-router-passport.json
host=$(jsonfilter -i "$passport" -e '@.host')
port=$(jsonfilter -i "$passport" -e '@.port')
fingerprint=$(dropbearkey -y -f /etc/dropbear/dropbear_ed25519_host_key |
    sed -n 's/^Fingerprint: SHA256://p' | tr -d '\r')
printf '%s\n' "$fingerprint" | grep -Eq '^[A-Za-z0-9+/]{43}$' || fail 'Не удалось прочитать отпечаток SSH.'
echo 'Роутер подготовлен. Вставь следующий код в ожидающий мастер на VPS:'
printf '\nxtls-pair-v1:%s:%s:%s\n\n' "$host" "$port" "$fingerprint"
echo 'Код содержит адрес и публичный отпечаток SSH; пароль и приватные ключи не передаются.'
