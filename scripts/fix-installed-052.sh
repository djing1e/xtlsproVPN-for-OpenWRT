#!/bin/sh
# Optional no-restart fix for the already installed 0.5.2 file deployment.
set -eu
umask 077
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
target=/usr/share/xray/lab_prepare.uc
expected=af6896dcc1bc64f0a7bedcd594fe45b935aa47c00a291670a53b02a9dc0eac4f
candidate="$HERE/package/xtlsprovpn/files/usr/share/xray/lab_prepare.uc"
[ "$(sha256sum "$target" | awk '{print $1}')" = "$expected" ] || { echo 'Версия prepare отличается; исправление отменено.';exit 1; }
mkdir -p /var/run/xray-lab-control
exec 9>/var/run/xray-lab-control/action.lock
flock -n 9 || { echo 'Другая операция выполняется';exit 1; }
backup=$(mktemp -d /etc/xtlspro-preserve-rules-backup.XXXXXX)
cp -p "$target" "$backup/lab_prepare.uc"
ucode -c -o "$backup/syntax-check.uc" "$candidate"
rm "$backup/syntax-check.uc"
cp "$candidate" "$target.new"
chmod 644 "$target.new"
mv "$target.new" "$target"
printf 'Сохранение личных правил исправлено. Копия: %s. Прокси не перезапускался.\n' "$backup"
