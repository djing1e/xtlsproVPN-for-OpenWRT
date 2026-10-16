#!/bin/sh
# Exercise the normal update entry points once from the actual cron daemon.
set -eu
umask 077
RUN=/var/run/xray-lab-control
LAST=/root/xtls-cron-test-last
case "${1:-arm}" in
worker)
    WORK=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    mkdir "$WORK/started" 2>/dev/null || exit 0
    date -u > "$WORK/started-at"
    pidof xray > "$WORK/pid-before" || :
    rc=0
    /usr/bin/xray-lab sync > "$WORK/subscription.log" 2>&1 || rc=$?
    printf '%s\n' "$rc" > "$WORK/subscription.result"
    rc=0
    /usr/bin/xray-lab-routing update > "$WORK/routing.log" 2>&1 || rc=$?
    printf '%s\n' "$rc" > "$WORK/routing.result"
    pidof xray > "$WORK/pid-after" || :
    date -u > "$WORK/finished-at"
    # Serialize with the product's schedule editor; remove only our exact entry.
    exec 9>"$RUN/schedule.lock"
    flock 9
    crontab -l > "$WORK/current.cron"
    awk -v tag="$(cat "$WORK/tag")" 'index($0,tag)==0 {print}' "$WORK/current.cron" > "$WORK/clean.cron"
    crontab "$WORK/clean.cron"
    : > "$WORK/done"
    exit 0
    ;;
verify)
    WORK=$(cat "$LAST")
    case "$WORK" in /root/xtls-cron-test.*) ;; *) exit 1;; esac
    [ -f "$WORK/done" ] || { echo "Not finished yet. Report: $WORK"; exit 1; }
    echo '--- Start / finish ---'
    cat "$WORK/started-at" "$WORK/finished-at"
    echo '--- Subscription ---'
    cat "$WORK/subscription.log"
    echo '--- Routing ---'
    cat "$WORK/routing.log"
    [ "$(cat "$WORK/subscription.result")" = 0 ]
    [ "$(cat "$WORK/routing.result")" = 0 ]
    echo '--- PID before / after ---'
    cat "$WORK/pid-before" "$WORK/pid-after"
    crontab -l > "$WORK/final.cron"
    ! grep -qF "$(cat "$WORK/tag")" "$WORK/final.cron"
    cmp "$WORK/original.cron" "$WORK/final.cron"
    sha256sum -c "$WORK/schedule-before.sha256"
    /usr/bin/ucode /usr/share/xray/lab/control.uc health > "$WORK/health.json"
    cat "$WORK/health.json"
    [ "$(jsonfilter -i "$WORK/health.json" -e '@.proxy_ok')" = true ]
    echo 'PASS: cron executed both updates successfully; test entry removed and original schedule preserved.'
    exit 0
    ;;
arm) ;;
*) echo 'Usage: test-schedule-cron-lab.sh arm|verify'; exit 2;;
esac
[ "$(id -u)" = 0 ] || exit 1
ip -4 addr show dev br-lan | awk '
    $1=="inet" && $2=="172.16.100.95/23" {found=1}
    END {exit !found}' || { echo 'This test requires LAB 172.16.100.95/23.'; exit 1; }
pidof crond >/dev/null || { echo 'cron is not running.'; exit 1; }
mkdir -p "$RUN"
exec 9>"$RUN/schedule.lock"
flock -n 9 || { echo 'Schedule is being edited.'; exit 1; }
WORK=$(mktemp -d /root/xtls-cron-test.XXXXXX)
crontab -l > "$WORK/original.cron"
! grep -qF '# xtls-cron-smoke-test:' "$WORK/original.cron" || {
    echo 'A previous cron test still has an entry; finish that test first.'; exit 1;
}
sha256sum /etc/config/xray_lab_schedule > "$WORK/schedule-before.sha256"
cp "$0" "$WORK/test.sh"
chmod 700 "$WORK/test.sh"
printf '# xtls-cron-smoke-test:%s\n' "${WORK##*/}" > "$WORK/tag"
cp "$WORK/original.cron" "$WORK/new.cron"
printf '* * * * * /bin/sh %s/test.sh worker >> %s/worker.log 2>&1 %s\n' \
    "$WORK" "$WORK" "$(cat "$WORK/tag")" >> "$WORK/new.cron"
printf '%s\n' "$WORK" > "$LAST.new"
mv "$LAST.new" "$LAST"
crontab "$WORK/new.cron"
echo "Armed one-shot cron test: $WORK"
echo 'Expected start: next minute boundary. Original six-hour jobs are unchanged.'
