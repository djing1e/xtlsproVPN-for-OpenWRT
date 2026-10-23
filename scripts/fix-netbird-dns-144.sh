#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || { echo 'Запустите от root';exit 1; }
root=${FX_DNS_HOTFIX_ROOT:-}
cd "$(dirname "$0")/files"
files='etc/init.d/xray_core usr/bin/xray-netbird-guard usr/share/xray/lab/netbird.uc usr/bin/xray-dns-bind usr/share/xray/lab/dns_bind.uc etc/uci-defaults/94-xtls-dns-bind'
mkdir -p "$root/var/run/xray-lab-control" "$root/var/run/xtlspro-netbird"
exec 8>"$root/var/run/xtlspro-netbird/action.lock"
flock -n 8 || { echo 'Дождитесь завершения операции NetBird';exit 1; }
exec 9>"$root/var/run/xray-lab-control/action.lock"
flock -n 9 || { echo 'Дождитесь завершения операции Xray';exit 1; }
version=$(apk info -v -e xtlsprovpn)
[ "$version" = xtlsprovpn-1.4.4-r1 ] || { echo 'Этот hotfix предназначен для xtlsprovpn-1.4.4-r1';exit 1; }
sha256sum -c ../FILES.sha256
for file in $files;do
    [ ! -L "$root/$file" ] || { echo "Недопустимая ссылка: $file";exit 1; }
    if [ -f "$root/$file" ];then
        want=$(sha256sum "$file");want=${want%% *}
        have=$(sha256sum "$root/$file");have=${have%% *}
        [ "$have" != "$want" ] || continue
        case "$file:$have" in
        etc/init.d/xray_core:bafb1920647e51d5a3af04bad6653326a659dd7ba70daf1b65db34ceedde7780) ;;
        usr/bin/xray-netbird-guard:219ffe1f527c687c60caaa6ea8c5cfc4051d42ed62e1f9ece7f23b0708cd379f) ;;
        usr/share/xray/lab/netbird.uc:7deb442361930169dbfeea6ee069aeff11cb2d13afa7abae858ec82ea8523f23) ;;
        *) echo "Неизвестная версия файла: $file";exit 1;;
        esac
    else
        case "$file" in usr/bin/xray-dns-bind|usr/share/xray/lab/dns_bind.uc|etc/uci-defaults/94-xtls-dns-bind) ;; *) exit 1;; esac
    fi
done
for file in etc/init.d/xray_core usr/bin/xray-netbird-guard usr/bin/xray-dns-bind etc/uci-defaults/94-xtls-dns-bind;do sh -n "$file";done
# The router has real UCI modules; compile before replacing anything.
work=$(mktemp -d /tmp/xtls-netbird-dns-check.XXXXXX)
backup=;changed=0;committed=0
finish() {
    rc=$?;trap - EXIT
    if [ "$changed" = 1 ] && [ "$committed" = 0 ];then
        for file in $files;do
            if [ -f "$backup/$file" ];then cp -p "$backup/$file" "$root/$file";else rm -f "$root/$file";fi
            rm -f "$root/$file.netbird-dns-new"
        done
    fi
    rm -rf "$work"
    exit "$rc"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
ucode -c -o "$work/bind.ucb" usr/share/xray/lab/dns_bind.uc
backup=$(mktemp -d "$root/root/xtls-before-netbird-dns.XXXXXX")
cp -p "$root/etc/config/dhcp" "$backup/dhcp.reference"
for file in $files;do
    mkdir -p "$backup/$(dirname "$file")"
    [ ! -e "$root/$file" ] || cp -p "$root/$file" "$backup/$file"
done
changed=1
for file in $files;do
    mkdir -p "$root/$(dirname "$file")"
    cp "$file" "$root/$file.netbird-dns-new"
    case "$file" in usr/share/*) chmod 644 "$root/$file.netbird-dns-new";; *) chmod 755 "$root/$file.netbird-dns-new";;esac
    mv "$root/$file.netbird-dns-new" "$root/$file"
done
committed=1
echo "Код установлен. Резервная копия: $backup"
# Apply only the DNS listener split. Do not reconnect NetBird or restart Xray.
if [ -z "$root" ];then
    /usr/bin/xray-dns-bind
    /etc/init.d/xray_netbird_guard restart
    sleep 3
    ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 udp
    ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 tcp
    echo 'DNS на 127.0.0.1:53 отвечает по UDP/TCP. Проверьте сайты на LAN-клиенте.'
fi
