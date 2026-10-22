#!/bin/sh
# Narrow correction for the verified v1.4.1 APK. No service restarts.
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
[ "$(apk info -v -e xtlsprovpn)" = 'xtlsprovpn-1.4.1-r1' ] || {
    echo 'Исправление предназначено только для установленного APK 1.4.1-r1.'; exit 1
}
lib=/usr/share/xray/lab
mkdir -p /var/run/xray-lab-control
exec 9>/var/run/xray-lab-control/action.lock
flock -n 9 || { echo 'Дождитесь завершения операции роутера.'; exit 1; }
work=$(mktemp -d /tmp/xtls-card-version.XXXXXX)
backup=''
changed=0
committed=0
finish() {
    if [ "$changed" = 1 ] && [ "$committed" = 0 ]; then
        cp -p "$backup/state.mjs" "$lib/state.mjs"
        cp -p "$backup/package_release.mjs" "$lib/package_release.mjs"
        echo 'Исходные файлы возвращены.'
    fi
    rm -rf "$work"
}
trap finish EXIT
trap 'exit 130' HUP INT TERM
ref=3f4136771191901a44239efc3397d9f0d0157322
base="https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/$ref/package/xtlsprovpn/files/usr/share/xray/lab"
for name in state.mjs package_release.mjs; do
    test -f "$lib/$name"
    test ! -L "$lib/$name"
    curl -fLsS --connect-timeout 10 --max-time 60 "$base/$name" -o "$work/$name"
done
cd "$work"
sha256sum -c - <<'SUMS'
c7bdb32436c9b01c7ab842c8713a247079785ea1fe7d7c0945634de3469ff57a  state.mjs
2220fd606778b1f4750a0e197b556347ea1c2f9d681332a2d67d87560979f828  package_release.mjs
SUMS
# Refuse to overwrite locally modified or unknown router code.
for name in state.mjs package_release.mjs; do
    current=$(sha256sum "$lib/$name"); current=${current%% *}
    target=$(sha256sum "$work/$name"); target=${target%% *}
    case "$name:$current" in
        state.mjs:54a323f03c80e961e2532a3054162bacae8e228ab53794b89290afc2e6bd5a57|package_release.mjs:372b03b93fec3a2035879fbb065c8675ecb8ad27a6fb5ec656e825ecfa1159b8) ;;
        *) [ "$current" = "$target" ] || { echo "Неизвестная версия файла: $name"; exit 1; } ;;
    esac
done
cp "$lib/operation_error.mjs" "$work/operation_error.mjs"
ucode -e "import { run_dir } from '$work/state.mjs'; import { installed_version } from '$work/package_release.mjs'; if (installed_version()!='1.4.1-r1') die('Не удалось прочитать версию APK');"
backup=$(mktemp -d /root/xtls-before-card-version.XXXXXX)
cp -p "$lib/state.mjs" "$lib/package_release.mjs" "$backup/"
changed=1
for name in package_release.mjs state.mjs; do
    cp "$work/$name" "$lib/$name.new"
    chmod 644 "$lib/$name.new"
    mv "$lib/$name.new" "$lib/$name"
done
committed=1
echo "Исправление установлено. Резервная копия: $backup"
echo 'Обновите карточку роутера в боте: версия должна стать 1.4.1-r1.'
