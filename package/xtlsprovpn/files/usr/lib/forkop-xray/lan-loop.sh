#!/bin/sh
# Independent lock: a slow subscription/list download must not delay cleanup.
umask 077
LIB=${FX_LIB:-/usr/lib/forkop-xray}
RUN=${FX_RUN_DIR:-/var/run/forkop-xray}
mkdir -p "$RUN"
exec 9>"$RUN/lan.lock"
flock -n 9 || exit 1
export FX_RUN_DIR="$RUN"
cleanup() {
    ucode -L "$LIB" -e "require('lan_runtime').cleanup(getenv('FX_RUN_DIR'));" >&2
}
trap cleanup EXIT
trap 'exit 0' TERM INT HUP
while :; do
    if ucode -L "$LIB" -e "require('lan_runtime').tick(getenv('FX_RUN_DIR'));" >&2; then
        sleep 1
    else
        sleep 5
    fi
done
