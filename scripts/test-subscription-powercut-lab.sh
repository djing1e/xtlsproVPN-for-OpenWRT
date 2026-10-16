#!/bin/sh
# Physical power-cut test for the isolated LAB; does not change node credentials.
set -eu
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
RUN=/var/run/xray-lab-control
STATE=/etc/forkop-xray
CORE=/etc/config/xray_core
CONTROL=/usr/share/xray/lab/control.uc
JOURNAL="$STATE/.subscription-transaction"
LAST=/root/xtls-power-test-last
MARKER=XTLS_POWERCUT_TEST_20261016
[ "$(id -u)" = 0 ] || exit 1
if ! ip -4 addr show dev br-lan | awk '
    $1=="inet" && $2=="172.16.100.95/23" {found=1}
    END {exit !found}'; then
    echo 'This test requires live br-lan address 172.16.100.95/23.' >&2
    exit 1
fi
exec 8>"$RUN/action.lock"
flock -n 8 || { echo 'Another operation is running.' >&2; exit 1; }
export FX_LOCK_HELD=1
case "${1:-arm}" in
verify)
    WORK=$(cat "$LAST")
    case "$WORK" in /root/xtls-power-test.*) ;; *) exit 1;; esac
    [ -f "$WORK/ready" ] || { echo 'FAIL: the test never reached its power-cut checkpoint.'; exit 1; }
    [ "$(cat /proc/sys/kernel/random/boot_id)" != "$(cat "$WORK/boot-id")" ] || {
        echo 'FAIL: router has not booted again since this test was armed.'; exit 1;
    }
    [ ! -e "$JOURNAL" ] || { echo 'FAIL: recovery journal remains pending; keep the backup.'; exit 1; }
    ! grep -q "$MARKER" "$CORE" || { echo 'FAIL: candidate alias remains in live config.'; exit 1; }
    sha256sum -c "$WORK/before.sha256"
    while IFS= read -r missing; do
        [ ! -e "$missing" ] || { echo "FAIL: originally absent file exists: $missing"; exit 1; }
    done < "$WORK/absent"
    logread -e 'Restored previous subscription configuration after an interrupted apply' > "$WORK/recovery.log"
    cat "$WORK/recovery.log"
    [ -s "$WORK/recovery.log" ] || { echo 'FAIL: boot recovery message not found.'; exit 1; }
    /usr/bin/ucode "$CONTROL" health > "$WORK/health-after.json"
    cat "$WORK/health-after.json"
    [ "$(jsonfilter -i "$WORK/health-after.json" -e '@.proxy_ok')" = true ] || exit 1
    if [ "$(uci -q get xray_lab_dns.main.ttl_enabled || :)" = 1 ]; then
        ttl=$(uci -q get xray_lab_dns.main.ttl)
        /usr/bin/ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 udp "$ttl"
        /usr/bin/ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 tcp "$ttl"
    fi
    echo 'PASS: new boot, interrupted apply restored, original files, HTTPS and DNS verified.'
    echo "Report and backup: $WORK"
    exit 0
    ;;
arm) ;;
*) echo 'Usage: test-subscription-powercut-lab.sh arm|verify' >&2; exit 2;;
esac
[ -x /usr/bin/xray-lab-subscription-journal ] || exit 1
/etc/init.d/xray_lab_recovery enabled || exit 1
/etc/init.d/xray_core enabled || exit 1
/etc/init.d/xray_core running || exit 1
[ "$(uci -q get xray_core.general.transparent_proxy_enable)" = 1 ] || exit 1
[ ! -e "$JOURNAL" ] && [ ! -f "$RUN/subscription-recovery" ] || {
    echo 'Resolve the previous transaction first.' >&2; exit 1;
}
! grep -q "$MARKER" "$CORE" || exit 1
WORK=$(mktemp -d /root/xtls-power-test.XXXXXX)
echo "Test report and backup: $WORK"
mkdir "$WORK/bin"
cp "$0" "$WORK/test.sh"
chmod 700 "$WORK/test.sh"
cat /proc/sys/kernel/random/boot_id > "$WORK/boot-id"
/usr/bin/ucode "$CONTROL" health > "$WORK/health-before.json"
[ "$(jsonfilter -i "$WORK/health-before.json" -e '@.proxy_ok')" = true ] || exit 1
# A second backup stays outside the package's own transaction directory.
tar -czf "$WORK/backup.tar.gz" -C / etc/config/xray_core etc/config/xray_lab_dns etc/config/dhcp etc/forkop-xray
: > "$WORK/before.sha256"
: > "$WORK/absent"
for file in "$CORE" /etc/config/xray_lab_dns /etc/config/dhcp /usr/libexec/forkop-xray/xray \
    "$STATE/subscription.json" "$STATE/previous.json" "$STATE/last-success-update" \
    "$STATE/device-hwid" "$STATE/device-hwid-short"; do
    if [ -f "$file" ]; then sha256sum "$file" >> "$WORK/before.sha256"
    else printf '%s\n' "$file" >> "$WORK/absent"; fi
done
printf '%s\n' "$WORK" > "$LAST.new"
mv "$LAST.new" "$LAST"
cat > "$WORK/mutate.uc" <<'UC'
let fs=require('fs');
let c=json(fs.readfile(ARGV[0]) || 'null');
if(!length(c?.nodes || []))die('No staged nodes');
c.nodes[0].name='XTLS_POWERCUT_TEST_20261016';
if(!fs.writefile(ARGV[0],sprintf('%J',c)))die('Cannot stage test alias');
UC
cat > "$WORK/bin/forkop-xray" <<'WRAP'
#!/bin/sh
set -eu
[ "$1" = update ] || exit 2
[ "$FX_STATE_DIR" != /etc/forkop-xray ] || exit 2
exec /usr/bin/ucode "$FX_TEST_ROOT/mutate.uc" "$FX_STATE_DIR/subscription.json"
WRAP
cat > "$WORK/bin/mv" <<'WRAP'
#!/bin/sh
set -eu
/bin/mv "$@"
if [ "$#" = 2 ] && [ "$1" = /etc/config/xray_core.sync-new ] && [ "$2" = /etc/config/xray_core ]; then
    journal=/etc/forkop-xray/.subscription-transaction
    [ -f "$journal/previous-core" ] && [ ! -e "$journal/committed" ] || exit 1
    grep -q XTLS_POWERCUT_TEST_20261016 /etc/config/xray_core || exit 1
    # At this checkpoint a candidate config is on flash, but no commit decision exists.
    : > "$FX_TEST_ROOT/ready"
    sync
    echo 'READY FOR POWER CUT: disconnect LAB power now; reconnect after 10 seconds.'
    echo 'Keep the internet cable connected. Do not issue reboot or stop.'
    count=0
    while [ "$count" -lt 150 ]; do
        sleep 2
        [ ! -f "$FX_TEST_ROOT/cancel" ] || break
        count=$((count+1))
    done
    echo 'Checkpoint cancelled or timed out; returning failure to trigger ordinary rollback.'
    exit 1
fi
WRAP
chmod 700 "$WORK/bin/forkop-xray" "$WORK/bin/mv"
sync
echo 'Preparing an alias-only candidate using the installed r5 updater.'
echo 'Disconnect power ONLY after READY FOR POWER CUT. Checkpoint expires after five minutes.'
# The pipeline streams the readiness message while retaining the test log.
PATH="$WORK/bin:$PATH" FX_TEST_ROOT="$WORK" /usr/bin/xray-lab-sync-safe 2>&1 | tee "$WORK/test.log"
echo 'No power cut occurred. Inspect the log for rollback; this is not a power-loss PASS.'
exit 1
