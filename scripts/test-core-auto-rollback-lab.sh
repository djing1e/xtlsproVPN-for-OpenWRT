#!/bin/sh
# Inject a post-switch health rejection only on the isolated LAB.
set -eu
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
BIN=/usr/libexec/forkop-xray/xray
RUN=/var/run/xray-lab-control
CONTROL=/usr/share/xray/lab/control.uc
TARGET=26.10.10
[ "$(id -u)" = 0 ] || exit 1
ip -4 addr show dev br-lan | awk '
    $1=="inet" && $2=="172.16.100.95/23" {found=1}
    END {exit !found}' || { echo 'This test requires LAB 172.16.100.95/23.'; exit 1; }
[ "$("$BIN" version | awk 'NR==1 {print $2}')" = 26.7.28 ] || {
    echo 'This test expects the original core 26.7.28.'; exit 1;
}
[ "$(uci -q get xray_core.general.transparent_proxy_enable)" = 1 ] || exit 1
/etc/init.d/xray_core running || exit 1
[ ! -e /etc/forkop-xray/.subscription-transaction ] || exit 1
exec 8>"$RUN/action.lock"
flock -n 8 || { echo 'Another operation is running.'; exit 1; }
WORK=$(mktemp -d /root/xtls-core-rollback-test.XXXXXX)
echo "Report and independent core backup: $WORK"
mkdir "$WORK/bin"
cp -p "$BIN" "$WORK/original-xray"
if [ -f "$BIN.previous" ] && [ ! -L "$BIN.previous" ]; then
    ln "$BIN.previous" "$WORK/saved-previous"
elif [ -e "$BIN.previous" ] || [ -L "$BIN.previous" ]; then
    echo 'Unexpected backup file type.'; exit 1
fi
sha256sum "$BIN" /etc/config/xray_core /etc/config/xray_lab_dns /etc/config/dhcp \
    /etc/forkop-xray/subscription.json > "$WORK/before.sha256"
/usr/bin/ucode "$CONTROL" health > "$WORK/health-before.json"
[ "$(jsonfilter -i "$WORK/health-before.json" -e '@.proxy_ok')" = true ] || exit 1
cat > "$WORK/bin/ucode" <<'WRAP'
#!/bin/sh
set -eu
if [ "${1:-}" = /usr/share/xray/lab/control.uc ] && [ "${2:-}" = health ] &&
   [ "$(/usr/libexec/forkop-xray/xray version | awk 'NR==1 {print $2}')" = "$FX_CORE_TEST_VERSION" ]; then
    echo rejected-candidate >> "$FX_TEST_ROOT/injections"
    echo '{"proxy_ok":false}'
    exit 0
fi
exec /usr/bin/ucode "$@"
WRAP
chmod 700 "$WORK/bin/ucode"
sync
# The installed updater acquires the same action lock itself. Do not inherit ours.
exec 8>&-
echo 'Expect a controlled health rejection after switching cores, then automatic rollback.'
echo 'Brief traffic interruptions are expected. Do not cut power in this test.'
(
    result=0
    PATH="$WORK/bin:$PATH" FX_CORE_TEST_VERSION="$TARGET" FX_TEST_ROOT="$WORK" \
        /usr/bin/xray-lab-core install "$TARGET" || result=$?
    printf '%s\n' "$result" > "$WORK/result"
) 2>&1 | tee "$WORK/test.log"
# Reacquire the lock for assertions and backup cleanup, never override a busy job.
exec 8>"$RUN/action.lock"
flock -n 8 || { echo "FAIL: another operation started; backup retained: $WORK"; exit 1; }
[ "$(cat "$WORK/result")" != 0 ] || { echo 'FAIL: expected an update failure.'; exit 1; }
[ -s "$WORK/injections" ] || { echo 'FAIL: post-switch injection was not reached.'; exit 1; }
cp "$RUN/core-update.json" "$WORK/updater-result.json"
cat "$WORK/updater-result.json"
[ "$(jsonfilter -i "$WORK/updater-result.json" -e '@.phase')" = rolled_back ] || {
    echo "FAIL: automatic rollback not confirmed. Rescue core: $WORK/original-xray"; exit 1;
}
sha256sum -c "$WORK/before.sha256"
verified=0
for attempt in 1 2 3 4 5; do
    if /usr/bin/ucode "$CONTROL" health > "$WORK/health-after.json" &&
       [ "$(jsonfilter -i "$WORK/health-after.json" -e '@.proxy_ok')" = true ] &&
       /usr/bin/ucode "$CONTROL" status > "$WORK/status-after.json" &&
       [ "$(jsonfilter -i "$WORK/status-after.json" -e '@.interception.active')" = true ]; then
        verified=1; break
    fi
    sleep 2
done
cat "$WORK/health-after.json"
[ "$verified" = 1 ] || { echo 'FAIL: restored core has not passed real health checks.'; exit 1; }
if [ "$(uci -q get xray_lab_dns.main.ttl_enabled || :)" = 1 ]; then
    ttl=$(uci -q get xray_lab_dns.main.ttl)
    /usr/bin/ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 udp "$ttl"
    /usr/bin/ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 tcp "$ttl"
fi
# Keep the backup that existed before this test. Do not change keep_previous preferences.
if [ -f "$WORK/saved-previous" ]; then
    ln "$WORK/saved-previous" "$BIN.previous.test-restore"
    mv -f "$BIN.previous.test-restore" "$BIN.previous"
else
    rm -f "$BIN.previous"
fi
sync
rm -f "$WORK/saved-previous"
echo 'PASS: injected post-switch failure, automatic core rollback, original files, HTTPS, DNS and interception verified.'
echo "Report and rescue core retained: $WORK"
