#!/bin/sh
# Exact, reversible application-only hotfix for the published v1.4.2-r1 APK.
set -eu
umask 077
[ "$(id -u)" = 0 ] || { echo 'Run as root';exit 1; }
[ "$(apk info -v -e xtlsprovpn)" = xtlsprovpn-1.4.2-r1 ] || { echo 'Expected xtlsprovpn-1.4.2-r1';exit 1; }
TARGET_ROOT=/
source_commit=8f82b52983a123d749915a3b0b35e0e222003dc0
work=$(mktemp -d /tmp/xtls-sub-tls.XXXXXX)
backup=
applied=0
mkdir -p /var/run/xray-lab-control
exec 8>/var/run/xray-lab-control/action.lock
flock -n 8 || { echo 'Another operation is running';rm -rf "$work";exit 1; }
finish() {
    rc=$?
    trap - EXIT HUP INT TERM
    if [ "$rc" != 0 ] && [ "$applied" = 1 ]; then
        while read -r rel old new mode; do
            target="$TARGET_ROOT$rel"
            if [ "$old" = absent ]; then rm -f "$target";else cp -p "$backup/$rel" "$target";fi
        done < "$work/manifest"
        echo "Hotfix rolled back. Backup: $backup"
    fi
    rm -rf "$work"
    exit "$rc"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
cat > "$work/manifest" <<'MANIFEST'
usr/share/xray/lab/subscription_transport.mjs absent 0bba5cd7788483afef18b61677e9cbac657a13a06a5dc023bc1f21ac9efcc478 644
usr/share/xray/lab/subscription_transport.uc absent 6c4e59a42f5b2a497c5c224c881e528105a63e96c44802581c3e31711659bc52 644
usr/lib/forkop-xray/main.uc f0de82ef9ce13438e2e406b32f835162198dc7c141e028b4f8a6a9a45c6fe436 f1131f6a4e7a7961d83cb5cb1b9fb4f7287bf2473c5867dbe2ad61cc2da5f31b 644
usr/bin/xray-lab-sync-safe 7e531c8d44cc6d55856919ebc3540def686f5c2a663e4233d6e6338d29b65f1f 1e93b5afc4a3ed057e99ddb7d26cf847685853a3c5199d9b6527873997735e6d 755
MANIFEST
complete=1
while read -r rel old new mode; do
    target="$TARGET_ROOT$rel"
    if [ -f "$target" ] && [ ! -L "$target" ]; then
        current=$(sha256sum "$target");current=${current%% *}
        [ "$current" != "$new" ] || continue
    fi
    complete=0
done < "$work/manifest"
if [ "$complete" = 1 ]; then echo 'Hotfix already installed.';exit 0;fi
# Refuse modified, symlinked or partially patched installations.
while read -r rel old new mode; do
    target="$TARGET_ROOT$rel"
    [ ! -L "$target" ] || { echo "Symlink target refused: $rel";exit 1; }
    if [ "$old" = absent ]; then
        [ ! -e "$target" ] || { echo "Unexpected existing file: $rel";exit 1; }
    else
        printf '%s  %s\n' "$old" "$target" | sha256sum -c -
    fi
    mkdir -p "$work/$(dirname "$rel")"
    curl -4 -fLsS --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 60 \
        "https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$source_commit/package/xtlsprovpn/files/$rel" -o "$work/$rel"
    printf '%s  %s\n' "$new" "$work/$rel" | sha256sum -c -
done < "$work/manifest"
sh -n "$work/usr/bin/xray-lab-sync-safe"
ucode -c -o "$work/check.ucb" "$work/usr/lib/forkop-xray/main.uc"
backup=$(mktemp -d /root/xtls-before-subscription-tls.XXXXXX)
while read -r rel old new mode; do
    if [ "$old" != absent ]; then
        mkdir -p "$backup/$(dirname "$rel")"
        cp -p "$TARGET_ROOT$rel" "$backup/$rel"
    fi
done < "$work/manifest"
cp "$work/manifest" "$backup/manifest"
applied=1
while read -r rel old new mode; do
    target="$TARGET_ROOT$rel"
    cp "$work/$rel" "$target.xtls-tls-new"
    chmod "$mode" "$target.xtls-tls-new"
    mv -f "$target.xtls-tls-new" "$target"
done < "$work/manifest"
while read -r rel old new mode; do
    printf '%s  %s\n' "$new" "$TARGET_ROOT$rel" | sha256sum -c -
done < "$work/manifest"
applied=0
echo "Hotfix installed. Backup: $backup"
echo 'Proxy was not restarted. Run xray-lab sync to refresh the subscription.'
