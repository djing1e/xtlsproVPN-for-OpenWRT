#!/bin/sh
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f /etc/xtlspro-bot/profile.json ] && [ -f /etc/xtlspro-bot/device-id ] || exit 0
[ ! -L /etc/xtlspro-bot ] || exit 1
if [ "${1:-}" = wait ]; then
    cleanup() { case "$base" in /tmp/xtls-bot-bundle.*) rm -rf "$base" ;; esac; }
    trap cleanup EXIT
    for attempt in $(seq 1 600); do
        if sh "$base/refresh.sh" once; then exit 0;else rc=$?;[ "$rc" = 75 ] || exit "$rc";fi
        sleep 3
    done
    exit 1
fi
exec 7>/var/run/xtlspro-bot-admin/action.lock
flock -n 7 || exit 75
exec 9>/var/run/xtlspro-netbird/action.lock
flock -n 9 || exit 75
exec 8>/var/run/xray-lab-control/action.lock
flock -n 8 || exit 75
work=$(mktemp -d /tmp/xtls-bot-refresh.XXXXXX)
trap 'rm -rf "$work"' EXIT
for file in ssh.uc admin.uc updates.uc onboard.uc; do ucode -c -o "$work/$file.ucb" "$base/$file";done
backup=$(mktemp -d /root/xtls-before-bot-refresh.XXXXXX)
for file in ssh.uc ssh-entry admin.uc admin-worker updates.uc update-worker onboard.uc; do
    [ ! -L "/etc/xtlspro-bot/$file" ] || exit 1
    if [ -f "/etc/xtlspro-bot/$file" ]; then cp -p "/etc/xtlspro-bot/$file" "$backup/$file";fi
done
finish() {
    rc=$?;trap - EXIT
    if [ "$rc" != 0 ]; then
        for file in ssh.uc ssh-entry admin.uc admin-worker updates.uc update-worker onboard.uc; do
            if [ -f "$backup/$file" ]; then
                cp -p "$backup/$file" "/etc/xtlspro-bot/$file.restore"
                mv "/etc/xtlspro-bot/$file.restore" "/etc/xtlspro-bot/$file"
            else rm -f "/etc/xtlspro-bot/$file";fi
            rm -f "/etc/xtlspro-bot/$file.new"
        done
    fi
    rm -rf "$work"
    exit "$rc"
}
trap finish EXIT
for file in ssh.uc ssh-entry admin.uc admin-worker updates.uc update-worker onboard.uc; do
    cp "$base/$file" "/etc/xtlspro-bot/$file.new"
    chmod 600 "/etc/xtlspro-bot/$file.new"
    case "$file" in ssh-entry|*worker) chmod 700 "/etc/xtlspro-bot/$file.new" ;; esac
done
for file in admin.uc admin-worker updates.uc update-worker onboard.uc ssh.uc ssh-entry; do
    mv "/etc/xtlspro-bot/$file.new" "/etc/xtlspro-bot/$file"
done
