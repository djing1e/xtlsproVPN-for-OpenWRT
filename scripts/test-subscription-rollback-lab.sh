#!/bin/sh
# Hardware test for the isolated 172.16.100.95 LAB, not a production updater.
set -eu
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
[ "$(id -u)" = 0 ] || exit 1
# UCI may store IPv4 with a CIDR suffix or as a list; guard on the live LAN.
if ! ip -4 addr show dev br-lan | awk '
    $1=="inet" && $2=="172.16.100.95/23" {found=1}
    END {exit !found}';then
    echo 'This test requires live br-lan address 172.16.100.95/23.' >&2
    exit 1
fi
RUN=/var/run/xray-lab-control
CORE=/etc/config/xray_core
CONTROL=/usr/share/xray/lab/control.uc
MARKER=XTLS_ROLLBACK_TEST_20261016
[ ! -f "$RUN/subscription-recovery" ] || { echo 'Resolve previous recovery first.' >&2; exit 1; }
[ "$(uci -q get xray_core.general.transparent_proxy_enable)" = 1 ] || exit 1
/etc/init.d/xray_core running || exit 1
! grep -q "$MARKER" "$CORE" || { echo 'Test marker already present.' >&2; exit 1; }
exec 8>"$RUN/action.lock"
flock -n 8 || { echo 'Another operation is running.' >&2; exit 1; }
export FX_LOCK_HELD=1
WORK=$(mktemp -d /root/xtls-rollback-test.XXXXXX)
echo "Test report and backup: $WORK"
mkdir "$WORK/bin"
cleanup() {
    rc=$?
    trap - EXIT HUP INT TERM
    rm -rf "$WORK/bin"
    rm -f "$WORK/mutate.uc"
    echo "Report and backup retained: $WORK"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
tar -czf "$WORK/backup.tar.gz" -C / etc/config/xray_core etc/config/xray_lab_dns etc/config/dhcp etc/forkop-xray
cat > "$WORK/restore.sh" <<'SH'
#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec 8>/var/run/xray-lab-control/action.lock
flock -n 8 || { echo 'Another operation is running'; exit 1; }
tar -xzf "$base/backup.tar.gz" -C /
/etc/init.d/xray_core restart 8>&-
SH
chmod 700 "$WORK/restore.sh"
sha256sum /etc/config/xray_core /etc/config/xray_lab_dns /etc/config/dhcp /etc/forkop-xray/subscription.json > "$WORK/before"
/usr/bin/ucode "$CONTROL" health > "$WORK/health-before.json"
[ "$(jsonfilter -i "$WORK/health-before.json" -e '@.proxy_ok')" = true ] || exit 1

cat > "$WORK/mutate.uc" <<'UC'
let fs=require('fs');
let c=json(fs.readfile(ARGV[0]) || 'null');
if(!length(c?.nodes || []))die('No staged nodes');
c.nodes[0].name='XTLS_ROLLBACK_TEST_20261016';
if(!fs.writefile(ARGV[0],sprintf('%J',c)))die('Cannot stage test alias');
UC
cat > "$WORK/bin/forkop-xray" <<'SH'
#!/bin/sh
set -eu
[ "$1" = update ] || exit 2
[ "$FX_STATE_DIR" != /etc/forkop-xray ] || exit 2
exec /usr/bin/ucode "$FX_TEST_ROOT/mutate.uc" "$FX_STATE_DIR/subscription.json"
SH
cat > "$WORK/bin/ucode" <<'SH'
#!/bin/sh
set -eu
if [ "${1:-}" = /usr/share/xray/lab/control.uc ] && [ "${2:-}" = health ] &&
   grep -q XTLS_ROLLBACK_TEST_20261016 /etc/config/xray_core; then
    echo injected >> "$FX_TEST_ROOT/injections"
    echo '{"proxy_ok":false}'
    exit 0
fi
exec /usr/bin/ucode "$@"
SH
chmod 700 "$WORK/bin/forkop-xray" "$WORK/bin/ucode"
echo 'Expect live validation failure followed by rollback. Brief traffic interruptions are possible.'
result=0
PATH="$WORK/bin:$PATH" FX_TEST_ROOT="$WORK" /usr/bin/xray-lab-sync-safe > "$WORK/test.log" 2>&1 || result=$?
cat "$WORK/test.log"
[ "$result" != 0 ] || { echo 'FAIL: expected a failed apply'; exit 1; }
test -s "$WORK/injections"
grep -q 'Live validation failed' "$WORK/test.log"
grep -q 'Previous configuration restored; HTTPS and DNS verified.' "$WORK/test.log"
[ ! -f "$RUN/subscription-recovery" ] || { echo 'FAIL: rollback is unresolved'; exit 1; }
sha256sum -c "$WORK/before"
/usr/bin/ucode "$CONTROL" health > "$WORK/health-after.json"
cat "$WORK/health-after.json"
[ "$(jsonfilter -i "$WORK/health-after.json" -e '@.proxy_ok')" = true ] || exit 1
if [ "$(uci -q get xray_lab_dns.main.ttl_enabled || :)" = 1 ];then
    ttl=$(uci -q get xray_lab_dns.main.ttl)
    /usr/bin/ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 udp "$ttl"
    /usr/bin/ucode /usr/share/xray/lab/dns_query.uc 53 ipv4 tcp "$ttl"
fi
echo 'PASS: injected post-apply failure, rollback, original files, HTTPS and DNS verified.'
