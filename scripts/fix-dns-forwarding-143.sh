#!/bin/sh
# Code-only correction for verified 1.4.3-r1 files. Services are not restarted.
set -eu
umask 077
[ "$(id -u)" = 0 ] || { echo 'Запустите от root';exit 1; }
[ "$(apk info -v -e xtlsprovpn)" = xtlsprovpn-1.4.3-r1 ] || { echo 'Требуется xtlsprovpn 1.4.3-r1';exit 1; }
root=${FX_DNS_HOTFIX_ROOT:-}
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$root/var/run/xray-lab-control"
exec 9>"$root/var/run/xray-lab-control/action.lock"
flock -n 9 || { echo 'Дождитесь завершения операции Xray';exit 1; }
cd "$source_dir/files"
sha256sum -c - <<'SUMS'
bafb1920647e51d5a3af04bad6653326a659dd7ba70daf1b65db34ceedde7780  etc/init.d/xray_core
5aafa505011fb015d3bf2e325cc9a86c164b6e7131953d102209e81652e024d1  usr/share/xray/lab/dns_forward.uc
be427ca91b5599b6262b0d57562e32cfe1522611969dc423b7817d21859e4621  usr/share/xray/lab/dns_query.uc
SUMS
files='etc/init.d/xray_core usr/share/xray/lab/dns_forward.uc usr/share/xray/lab/dns_query.uc'
for file in $files;do
    target="$root/$file"
    [ ! -L "$target" ] || { echo "Symlink refused: $file";exit 1; }
    if [ -e "$target" ];then
        current=$(sha256sum "$target");current=${current%% *}
        case "$file:$current" in
            etc/init.d/xray_core:aaea58c386adbd59147f1dfebcde417a785944a3143c1846c82e3449ee6986e1|etc/init.d/xray_core:bafb1920647e51d5a3af04bad6653326a659dd7ba70daf1b65db34ceedde7780|usr/share/xray/lab/dns_forward.uc:5aafa505011fb015d3bf2e325cc9a86c164b6e7131953d102209e81652e024d1|usr/share/xray/lab/dns_query.uc:7ebd1747911c05bcfa1854ab1a885ce1041ccf0e864aef60340d6b13fc286af9|usr/share/xray/lab/dns_query.uc:be427ca91b5599b6262b0d57562e32cfe1522611969dc423b7817d21859e4621) ;;
            *) echo "Неизвестная версия файла: $file";exit 1;;
        esac
    else [ "$file" = usr/share/xray/lab/dns_forward.uc ] || exit 1;fi
done
work=$(mktemp -d /tmp/xtls-dns-forward-check.XXXXXX)
backup=;changed=0;committed=0
finish() {
    rc=$?;trap - EXIT
    if [ "$changed" = 1 ] && [ "$committed" = 0 ];then
        for file in $files;do
            if [ -f "$backup/$file" ];then cp -p "$backup/$file" "$root/$file";else rm -f "$root/$file";fi
            rm -f "$root/$file.dns-fix-new"
        done
    fi
    rm -rf "$work"
    exit "$rc"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
sh -n etc/init.d/xray_core
cp "$root/usr/share/xray/lab/dns_wire.mjs" "$work/dns_wire.mjs"
cp usr/share/xray/lab/dns_query.uc "$work/dns_query.uc"
ucode -c -o "$work/query.ucb" "$work/dns_query.uc"
ucode -c -o "$work/forward.ucb" usr/share/xray/lab/dns_forward.uc
backup=$(mktemp -d "$root/root/xtls-before-dns-forward.XXXXXX")
for file in $files;do
    mkdir -p "$backup/$(dirname "$file")"
    [ ! -e "$root/$file" ] || cp -p "$root/$file" "$backup/$file"
done
cp -p "$root/etc/config/dhcp" "$backup/dhcp.reference"
changed=1
for file in $files;do
    cp "$file" "$root/$file.dns-fix-new"
    case "$file" in etc/init.d/*) chmod 755 "$root/$file.dns-fix-new";; *) chmod 644 "$root/$file.dns-fix-new";;esac
    mv "$root/$file.dns-fix-new" "$root/$file"
done
committed=1
echo "Исправление кода установлено. Резервная копия: $backup"
echo 'Службы и настройки не изменены. Теперь повторите применение DNS в LuCI.'
