#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
dest=/etc/xtlspro-bot
bundle=/usr/share/xray/bot
test -f "$dest/profile.json"
test -f "$dest/ssh.uc"
test -f "$bundle/bundle.sha256"
work=$(mktemp -d /tmp/xtls-hwid-bridge.XXXXXX)
trap 'rm -rf "$work"' EXIT
curl -fLsS --connect-timeout 10 --max-time 60 \
    https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/ef1198ee8682dde2b6592997635b1e4f7d118b8c/integrations/router-bot/router/ssh.uc \
    -o "$work/ssh.uc"
hash=78f654f567764caba97d1d7619ed2383d7cd387a8bb78ebdb221b579ebec43b3
printf '%s  %s\n' "$hash" "$work/ssh.uc" | sha256sum -c -
ucode -c -o "$work/check.ucb" "$work/ssh.uc"
mkdir -p /var/run/xtlspro-bot-admin /var/run/xtlspro-netbird /var/run/xray-lab-control
exec 7>/var/run/xtlspro-bot-admin/action.lock
flock -n 7
exec 9>/var/run/xtlspro-netbird/action.lock
flock -n 9
exec 8>/var/run/xray-lab-control/action.lock
flock -n 8
(cd "$bundle"; sha256sum -c bundle.sha256 >/dev/null)
backup=$(mktemp -d /root/xtls-before-hwid-bridge.XXXXXX)
cp -p "$dest/ssh.uc" "$backup/private.uc"
cp -p "$bundle/ssh.uc" "$backup/bundle.uc"
cp -p "$bundle/bundle.sha256" "$backup/bundle.sha256"
finish() {
    rc=$?
    trap - EXIT
    if [ "$rc" != 0 ]; then
        cp -p "$backup/private.uc" "$dest/ssh.uc"
        cp -p "$backup/bundle.uc" "$bundle/ssh.uc"
        cp -p "$backup/bundle.sha256" "$bundle/bundle.sha256"
    fi
    rm -f "$dest/ssh.uc.new" "$bundle/ssh.uc.new" "$bundle/bundle.sha256.new"
    rm -rf "$work"
    exit "$rc"
}
trap finish EXIT
cp "$work/ssh.uc" "$bundle/ssh.uc.new"
chmod 644 "$bundle/ssh.uc.new"
mv "$bundle/ssh.uc.new" "$bundle/ssh.uc"
awk -v hash="$hash" '$2=="ssh.uc" {$1=hash} {print $1 "  " $2}' \
    "$bundle/bundle.sha256" > "$bundle/bundle.sha256.new"
chmod 644 "$bundle/bundle.sha256.new"
mv "$bundle/bundle.sha256.new" "$bundle/bundle.sha256"
(cd "$bundle"; sha256sum -c bundle.sha256 >/dev/null)
cp "$work/ssh.uc" "$dest/ssh.uc.new"
chmod 600 "$dest/ssh.uc.new"
mv "$dest/ssh.uc.new" "$dest/ssh.uc"
echo "HWID доступен боту. Резервная копия: $backup"
