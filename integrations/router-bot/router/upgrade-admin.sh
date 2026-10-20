#!/bin/sh
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dest=/etc/xtlspro-bot
[ "$(id -u)" = 0 ]
[ -d "$dest" ] && [ ! -L "$dest" ] && [ -x "$dest/ssh-entry" ]
for file in ssh.uc admin.uc admin-worker; do
    [ -s "$base/$file" ]
    [ ! -L "$dest/$file" ]
done
sh -n "$base/admin-worker"
check=$(mktemp -d /tmp/xtls-bot-admin-check.XXXXXX)
trap 'rm -rf "$check"' EXIT
ucode -c -o "$check/ssh.ucb" "$base/ssh.uc"
ucode -c -o "$check/admin.ucb" "$base/admin.uc"
mkdir -p /var/run/xtlspro-bot-admin
exec 7>/var/run/xtlspro-bot-admin/action.lock
flock -n 7 || { echo 'Административное задание выполняется — остановка.'; exit 1; }
backup=$(mktemp -d /root/xtls-before-bot-admin.XXXXXX)
for file in ssh.uc admin.uc admin-worker; do
    if [ -f "$dest/$file" ]; then cp -p "$dest/$file" "$backup/$file"; fi
done
rollback() {
    rc=$?
    trap - EXIT
    if [ "$rc" != 0 ]; then
        for file in ssh.uc admin.uc admin-worker; do
            if [ -f "$backup/$file" ]; then cp -p "$backup/$file" "$dest/$file"; else rm -f "$dest/$file"; fi
        done
        echo 'Обработчик восстановлен из резервной копии.'
    fi
    rm -rf "$check"
    exit "$rc"
}
trap rollback EXIT
for file in admin.uc admin-worker ssh.uc; do
    cp "$base/$file" "$dest/$file.new"
    chmod 600 "$dest/$file.new"
    [ "$file" != admin-worker ] || chmod 700 "$dest/$file.new"
    mv "$dest/$file.new" "$dest/$file"
done
SSH_ORIGINAL_COMMAND='xtlsbot-v1 admin-status' "$dest/ssh-entry"
printf '\nРезервная копия: %s\n' "$backup"
