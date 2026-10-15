#!/bin/sh
# Each operation takes the shared CLI lock. Probe failures retain selection.
while sleep 10; do
    /usr/bin/forkop-xray routing-tick >/dev/null 2>&1 || :
    /usr/bin/forkop-xray update-due >/dev/null 2>&1 || :
    /usr/bin/forkop-xray routing-refresh-due >/dev/null 2>&1 || :
done
