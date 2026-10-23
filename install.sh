#!/bin/sh
# Published stable release; bump version, URL and hash together.
set -eu
MODE=install
VERSION='1.4.5-r1'
SHA256='ed0a0569208dbf85bfc1887b8b6fcbf1a2999edb681673de5e4b64f56ba2c264'
URL="https://github.com/djing1e/xtlsproVPN-for-OpenWRT/releases/download/v1.4.5/xtlsprovpn-$VERSION.apk"

fail() { echo "xtlsproVPN: $*" >&2; exit 1; }
[ "$#" -eq 0 ] || fail 'Параметры не поддерживаются.'
[ "$(id -u)" = 0 ] || fail 'Запустите от root.'
[ -f /etc/openwrt_release ] || fail 'Нужен OpenWrt.'
. /etc/openwrt_release
case "${DISTRIB_RELEASE:-}" in
    25.12.5|25.12.6) ;;
    *) fail 'Этот выпуск предназначен для OpenWrt 25.12.5/25.12.6.' ;;
esac
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
umask 077
workdir=$(mktemp -d /tmp/xtls-install.XXXXXX)
trap 'rm -rf "$workdir"' EXIT
trap 'exit 1' HUP INT TERM
# OpenWrt apk delegates downloads to wget. Keep the IPv4 override local to
# this installer; no system downloader or network configuration is replaced.
fetch=$(command -v uclient-fetch || true)
if [ -n "$fetch" ]; then
    printf '#!/bin/sh\nexec "%s" -4 "$@"\n' "$fetch" > "$workdir/wget"
    chmod 700 "$workdir/wget"
fi
apk_run() {
    if [ -n "$fetch" ]; then
        PATH="$workdir:$PATH" apk --preserve-env "$@"
    else
        apk "$@"
    fi
}
apk_run update
apk_run add curl ca-bundle coreutils-sha256sum
package="$workdir/xtlsprovpn-$VERSION.apk"
curl -4 -fL --connect-timeout 10 --max-time 120 "$URL" -o "$package"
printf '%s  %s\n' "$SHA256" "$package" | sha256sum -c -
apk_run add --allow-untrusted "$package"
echo "xtlsproVPN $VERSION: установка пакета завершена."
echo 'Откройте Services → xtlsproVPN в LuCI. Ядро Xray управляется отдельно.'

