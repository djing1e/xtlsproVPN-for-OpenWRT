#!/bin/sh
set -eu
umask 077
fail() { echo "Bridge: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || fail 'Run as root on the test router'
[ "$#" = 1 ] || fail 'Usage: install.sh PUBLIC_KEY_FILE'
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for file in "$base/ssh.uc" "$base/ssh-entry" "$1"; do
    [ -s "$file" ] || fail "Missing file: $file"
done
command -v ucode >/dev/null || fail 'ucode required'
[ -x /usr/bin/xray-lab-control ] || fail 'xtlsproVPN controller required'
auth=/etc/dropbear/authorized_keys
[ -d "$(dirname "$auth")" ] || fail 'OpenWrt Dropbear directory required'
if [ -e "$auth" ] || [ -L "$auth" ]; then
    [ -f "$auth" ] || fail 'authorized_keys must be a regular file or valid file symlink'
fi
[ ! -L /etc/xtlspro-bot ] || fail 'Refusing symlink directory'
key=$(awk 'NF { print $1 " " $2 }' < "$1")
[ "$(printf '%s\n' "$key" | wc -l)" -eq 1 ] || fail 'Expected one key, not multiple lines'
printf '%s\n' "$key" | grep -Eq '^ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI[A-Za-z0-9+/]{43}$' || fail 'Expected exactly one Ed25519 public key'
material=${key#ssh-ed25519 }
entry="command=\"/etc/xtlspro-bot/ssh-entry\",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty $key xtls-router-bot"
if [ -f "$auth" ] && grep -Fq "$material" "$auth"; then
    grep -Fxq "$entry" "$auth" || fail 'This key already exists with different options; inspect it manually'
fi
sh -n "$base/ssh-entry"
backup=$(mktemp -d /root/xtls-before-bot-bridge.XXXXXX)
if [ -f "$auth" ]; then
    cp -p "$auth" "$backup/authorized_keys"
else
    : > "$backup/authorized_keys.absent"
fi
if [ -d /etc/xtlspro-bot ]; then cp -R /etc/xtlspro-bot "$backup/bridge"; fi
mkdir -p /etc/xtlspro-bot
chmod 700 /etc/xtlspro-bot
cp "$base/ssh.uc" /etc/xtlspro-bot/ssh.uc.new
cp "$base/ssh-entry" /etc/xtlspro-bot/ssh-entry.new
chown root:root /etc/xtlspro-bot /etc/xtlspro-bot/ssh.uc.new /etc/xtlspro-bot/ssh-entry.new
chmod 600 /etc/xtlspro-bot/ssh.uc.new
chmod 700 /etc/xtlspro-bot/ssh-entry.new
mv /etc/xtlspro-bot/ssh.uc.new /etc/xtlspro-bot/ssh.uc
mv /etc/xtlspro-bot/ssh-entry.new /etc/xtlspro-bot/ssh-entry
if ! grep -Fxq "$entry" "$auth" 2>/dev/null; then
    printf '\n%s\n' "$entry" >> "$auth"
fi
chmod 600 "$auth"
echo "Bridge installed. Backup: $backup"
echo 'No service restart required. Test both permitted and rejected commands.'
