#!/bin/sh
# Published stable release; bump version, URL and hash together.
set -eu
MODE=install
VERSION='1.4.0-r1'
SHA256='15f20b62714a03e05862582652f553d7854fd76f65cd7813695edbc417e63821'
URL="https://github.com/djing1e/xtlsproVPN-for-OpenWRT/releases/download/v1.4.0/xtlsprovpn-$VERSION.apk"

fail() { echo "xtlsproVPN: $*" >&2; exit 1; }
[ "$#" -eq 0 ] || fail 'Параметры не поддерживаются.'
[ "$(id -u)" = 0 ] || fail 'Запустите от root.'
[ -f /etc/openwrt_release ] || fail 'Нужен OpenWrt.'
. /etc/openwrt_release
[ "${DISTRIB_RELEASE:-}" = '25.12.5' ] || fail 'Этот выпуск проверен для OpenWrt 25.12.5.'
[ "$(uname -m)" = aarch64 ] || fail 'Этот выпуск предназначен для aarch64.'
command -v apk >/dev/null 2>&1 || fail 'Не найден пакетный менеджер apk.'

installed=0
apk info -e xtlsprovpn >/dev/null 2>&1 && installed=1
case "$MODE:$installed" in
    install:1) fail 'Пакет уже установлен. Используйте ссылку обновления.' ;;
    update:0) fail 'Пакет не установлен. Используйте ссылку чистой установки.' ;;
esac
if [ "$MODE" = update ]; then
    if apk info -e "xtlsprovpn>$VERSION" >/dev/null 2>&1; then
        fail 'Установлена более новая версия; понижение не выполняется.'
    fi
    if apk info -e "xtlsprovpn=$VERSION" >/dev/null 2>&1; then
        echo "xtlsproVPN $VERSION уже установлен. Обновление не требуется."
        exit 0
    fi
fi

# No removal, purge, config reset or direct service restart.
apk update
apk add curl ca-bundle coreutils-sha256sum
umask 077
workdir=$(mktemp -d /tmp/xtls-install.XXXXXX)
trap 'rm -rf "$workdir"' EXIT
trap 'exit 1' HUP INT TERM
package="$workdir/xtlsprovpn-$VERSION.apk"
curl -fL --connect-timeout 10 --max-time 120 "$URL" -o "$package"
printf '%s  %s\n' "$SHA256" "$package" | sha256sum -c -
apk add --allow-untrusted "$package"
echo "xtlsproVPN $VERSION: установка пакета завершена."
echo 'Откройте Services → xtlsproVPN в LuCI. Ядро Xray управляется отдельно.'

