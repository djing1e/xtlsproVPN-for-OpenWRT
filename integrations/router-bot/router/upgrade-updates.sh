#!/bin/sh
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dest=/etc/xtlspro-bot
native=/usr/share/xray/lab/netbird.uc
[ "$(id -u)" = 0 ]
[ -d "$dest" ] && [ ! -L "$dest" ] && [ -x "$dest/ssh-entry" ] && [ -f "$dest/admin.uc" ]
[ -f "$native" ] && [ ! -L "$native" ]
for file in ssh.uc updates.uc update-worker admin-worker; do
    [ -s "$base/$file" ] && [ ! -L "$dest/$file" ]
done
sh -n "$base/admin-worker"
sh -n "$base/update-worker"
check=$(mktemp -d /tmp/xtls-bot-updates-check.XXXXXX)
trap 'rm -rf "$check"' EXIT
ucode -c -o "$check/ssh.ucb" "$base/ssh.uc"
ucode -c -o "$check/updates.ucb" "$base/updates.uc"
ucode "$base/updates.uc" patch-netbird "$native" "$check/netbird.uc"
ucode -c -o "$check/netbird.ucb" "$check/netbird.uc"
mkdir -p /var/run/xtlspro-bot-admin /var/run/xray-lab-control /var/run/xtlspro-netbird
exec 7>/var/run/xtlspro-bot-admin/action.lock
flock -n 7 || { echo 'Административное задание выполняется — остановка.'; exit 1; }
exec 9>/var/run/xtlspro-netbird/action.lock
flock -n 9 || { echo 'Операция NetBird выполняется — повтори позже.'; exit 1; }
exec 8>/var/run/xray-lab-control/action.lock
flock -n 8 || { echo 'Операция приложения выполняется — повтори позже.'; exit 1; }
backup=$(mktemp -d /root/xtls-before-bot-updates.XXXXXX)
cp -p "$native" "$backup/netbird.uc"
for file in ssh.uc updates.uc update-worker admin-worker; do
    if [ -f "$dest/$file" ]; then cp -p "$dest/$file" "$backup/$file"; fi
done
rollback() {
    rc=$?;trap - EXIT
    if [ "$rc" != 0 ]; then
        cp -p "$backup/netbird.uc" "$native"
        for file in ssh.uc updates.uc update-worker admin-worker; do
            if [ -f "$backup/$file" ]; then cp -p "$backup/$file" "$dest/$file"; else rm -f "$dest/$file"; fi
        done
        echo 'Предыдущие обработчики восстановлены.'
    fi
    rm -rf "$check"
    exit "$rc"
}
trap rollback EXIT
# Preserve the native file's ownership and mode; only add version binding.
cp -p "$native" "$native.new"
cat "$check/netbird.uc" > "$native.new"
mv "$native.new" "$native"
for file in updates.uc update-worker admin-worker ssh.uc; do
    cp "$base/$file" "$dest/$file.new"
    chmod 600 "$dest/$file.new"
    case "$file" in *worker) chmod 700 "$dest/$file.new" ;; esac
    mv "$dest/$file.new" "$dest/$file"
done
SSH_ORIGINAL_COMMAND='xtlsbot-v1 updates' "$dest/ssh-entry"
printf '\nРезервная копия: %s\n' "$backup"
