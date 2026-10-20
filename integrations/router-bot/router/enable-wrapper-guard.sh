#!/bin/sh
# Adopt an already connected legacy NetBird wrapper without reconnecting it.
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
wrapper=/etc/init.d/netbird-wrapper
guard=/etc/init.d/xray_netbird_guard
config=/etc/config/xray_lab_netbird
lib=/usr/share/xray/lab
test -x "$wrapper"
"$wrapper" enabled
test -x "$guard"
test -z "$(uci changes xray_lab_netbird)"
work=$(mktemp -d /tmp/xtls-wrapper-guard.XXXXXX)
trap 'rm -rf "$work"' EXIT
netbird status --json > "$work/status.json"
test "$(jsonfilter -i "$work/status.json" -e '@.management.connected')" = true
test "$(jsonfilter -i "$work/status.json" -e '@.signal.connected')" = true
url=$(jsonfilter -i "$work/status.json" -e '@.management.url')
printf '%s\n' "$url" | grep -Eq '^https://[A-Za-z0-9][A-Za-z0-9.:-]*(/[A-Za-z0-9._~/%-]*)?$'
for name in netbird.uc netbird_guard.uc; do
    file="$lib/$name"
    if grep -Fxq "const SERVICE='/etc/init.d/netbird';" "$file"; then
        sed "s@const SERVICE='/etc/init.d/netbird';@const SERVICE=cursor().get_all('xray_lab_netbird','main')?.service=='netbird-wrapper' ? '/etc/init.d/netbird-wrapper' : '/etc/init.d/netbird';@" \
            "$file" > "$work/$name"
    elif grep -Fq "?.service=='netbird-wrapper'" "$file"; then
        cp "$file" "$work/$name"
    else
        echo 'Неизвестная версия обработчика — изменения не применены.'
        exit 1
    fi
    if [ "$name" = netbird.uc ]; then
        sed 's/return {installed:/return {service:SERVICE,installed:/' "$work/$name" > "$work/status.uc"
        mv "$work/status.uc" "$work/$name"
    fi
    ucode -c -o "$work/$name.ucb" "$work/$name"
done
mkdir -p /var/run/xtlspro-bot-admin /var/run/xtlspro-netbird /var/run/xray-lab-control
exec 7>/var/run/xtlspro-bot-admin/action.lock
flock -n 7
exec 9>/var/run/xtlspro-netbird/action.lock
flock -n 9
exec 8>/var/run/xray-lab-control/action.lock
flock -n 8
before=$(pidof netbird)
guard_enabled=0; "$guard" enabled && guard_enabled=1
guard_running=0; "$guard" running && guard_running=1
backup=$(mktemp -d /root/xtls-before-wrapper-guard.XXXXXX)
cp -p "$config" "$backup/config"
cp -p "$lib/netbird.uc" "$backup/netbird.uc"
cp -p "$lib/netbird_guard.uc" "$backup/netbird_guard.uc"
finish() {
    rc=$?; trap - EXIT
    if [ "$rc" != 0 ]; then
        uci revert xray_lab_netbird || :
        cp -p "$backup/config" "$config"
        cp -p "$backup/netbird.uc" "$lib/netbird.uc"
        cp -p "$backup/netbird_guard.uc" "$lib/netbird_guard.uc"
        if [ "$guard_enabled" = 0 ]; then "$guard" disable || :;fi
        if [ "$guard_running" = 0 ]; then "$guard" stop || :;fi
    fi
    rm -f "$lib/netbird.uc.new" "$lib/netbird_guard.uc.new"
    rm -rf "$work"
    exit "$rc"
}
trap finish EXIT
for name in netbird.uc netbird_guard.uc; do
    cp -p "$lib/$name" "$lib/$name.new"
    cat "$work/$name" > "$lib/$name.new"
    mv "$lib/$name.new" "$lib/$name"
done
uci set xray_lab_netbird.main.service=netbird-wrapper
uci set xray_lab_netbird.main.enabled=1
saved=$(uci -q get xray_lab_netbird.main.management_url || :)
if [ -z "$saved" ]; then uci set "xray_lab_netbird.main.management_url=$url";fi
uci commit xray_lab_netbird
"$guard" enable
"$guard" start
"$guard" running
echo "Резервная копия: $backup"
echo "Guard включён; служба восстановления: netbird-wrapper."
echo "PID NetBird до: $before"
echo "PID NetBird после: $(pidof netbird)"
