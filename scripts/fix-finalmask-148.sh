#!/bin/sh
# Importer-only hotfix. Live services and subscription data are retained.
set -eu
umask 077
[ "$(id -u)" = 0 ]
[ "$(apk info -v -e xtlsprovpn)" = xtlsprovpn-1.4.8-r1 ] || {
    echo 'Этот фикс предназначен для xtlsproVPN 1.4.8-r1.';exit 1;
}
root=${FX_FINALMASK_ROOT:-}
target="$root/usr/lib/forkop-xray/parser.uc"
[ -f "$target" ] && [ ! -L "$target" ] || exit 1
old=f515bf0c26d71055c4bb06f1dfe371b21cb65241a55a7913ac1b3c80bc74d4f6
new=ff4f04f8842ad5b4117fd9b47561546f17b5cba016d93532481be75c399d7a39
actual=$(sha256sum "$target");actual=${actual%% *}
if [ "$actual" = "$new" ];then echo 'Поддержка FinalMask уже установлена. Обновите подписку.';exit 0;fi
[ "$actual" = "$old" ] || { echo 'Импортёр отличается от проверенной версии. Установка отменена.';exit 1; }
work=$(mktemp -d /tmp/xtls-finalmask.XXXXXX)
backup=
installing=0
cleanup() {
    rc=$?;trap - EXIT
    if [ "$rc" != 0 ] && [ "$installing" = 1 ];then
        cp -p "$backup" "$target.finalmask-new"
        mv -f "$target.finalmask-new" "$target"
        echo 'Предыдущий импортёр восстановлен.'
    fi
    rm -rf "$work"
    exit "$rc"
}
trap cleanup EXIT
curl -q -4 --noproxy '*' -fL --connect-timeout 10 --max-time 60 \
    https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/9adbfe39b98267e0cc2c4510ba27f9ef5cb5ad85/package/xtlsprovpn/files/usr/lib/forkop-xray/parser.uc \
    -o "$work/parser.uc"
printf '%s  %s\n' "$new" "$work/parser.uc" | sha256sum -c -
ucode -c -o "$work/parser.ucb" "$work/parser.uc"
mkdir -p "$root/var/run/xray-lab-control"
exec 9>"$root/var/run/xray-lab-control/action.lock"
flock -n 9 || { echo 'Дождитесь завершения операции роутера и повторите установку.';exit 1; }
# Download/compile may take time: recheck the file under the operation lock.
[ -f "$target" ] && [ ! -L "$target" ] || exit 1
actual=$(sha256sum "$target");actual=${actual%% *}
if [ "$actual" = "$new" ];then echo 'Поддержка FinalMask уже установлена.';exit 0;fi
[ "$actual" = "$old" ] || { echo 'Импортёр изменился во время подготовки. Установка отменена.';exit 1; }
backup=$(mktemp "$root/root/xtls-parser-before-finalmask.XXXXXX")
cp -p "$target" "$backup"
installing=1
cp "$work/parser.uc" "$target.finalmask-new"
chmod 644 "$target.finalmask-new"
mv -f "$target.finalmask-new" "$target"
installing=0
echo "Поддержка FinalMask установлена. Резервная копия: $backup"
echo 'Службы и настройки не изменены. Теперь обновите подписку в LuCI.'
