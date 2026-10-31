#!/bin/sh
# Apply only to the reviewed 1.4.7 application files. Router/LAB rollout is explicit.
set -eu
umask 077
[ "$(id -u)" = 0 ]
[ "$(apk info -v -e xtlsprovpn)" = xtlsprovpn-1.4.7-r1 ] || {
    echo 'Этот фикс предназначен для xtlsproVPN 1.4.7-r1.'; exit 1;
}
work=$(mktemp -d /tmp/xtls-failopen.XXXXXX)
backup=
installing=0
monitor=0
cleanup() {
    rc=$?;trap - EXIT
    if [ "$rc" != 0 ] && [ "$installing" = 1 ]; then
        while read -r old new path; do
            cp -p "$backup/$path" "/$path.failopen-new"
            mv "/$path.failopen-new" "/$path"
        done < "$work/manifest"
        if [ "$monitor" = 1 ];then /etc/init.d/xray_lab_monitor restart 8>&- 9>&- || :;fi
        echo 'Предыдущий код восстановлен.'
    fi
    rm -rf "$work"
    exit "$rc"
}
trap cleanup EXIT
cat > "$work/manifest" <<'MANIFEST'
10b64d04abaab7c1aaf5d5f116b44c68a400980614c3f2172df1519b389128e6 ea088b771b04b3648f7e3e679299916cf86d1c66478c7344aaf0d45f49a765a3 etc/init.d/xray_core
02fa3d03a1a79769cd55dc866ef1a49e7000a68d5e330a5eed652f29eeca508b 4ff82902bce6a86cc20de7f92035c8c40ad2839227b86c5a1c47f7f38b86d890 usr/bin/xray-lab
4f42d58eefb8e9528adea12136dc3de589fab355f69f77d0fa42db85b5448b81 8039f53b4d31e5ed8c6bc355b2f9ecc2d60172b53a0588062a3185acbad30ce2 usr/bin/xray-lab-control
a96e764a0a76eb2122ce19ac0d8ad36b5c87c4daf0e3298f782d294bb987baff 80343b7df485757c20d4acea3bc703e686b3b9024650cf2c70349c2719cb6331 usr/bin/xray-lab-sync-safe
b0dd759d2b58f5acfdbfbddd3d086416365356480668be532e24ab3855e7d6eb 4f235942f851fd6654fa7640f1ef6d7343a2f7561c2e1eaa5f458518593dceb9 usr/share/xray/lab/control.uc
fffbb256dc555b283b35e717c4b5ee9b3f669a143f2b6131c8e9789bd4aa7b18 23212498f7578d11c65a8ad602fce22f9d11ffdf1e9378dc96531ae4234c717f usr/share/xray/lab/state.mjs
f315bec44d1673783bcebf5c00d9a630bdfa04d86e70b678ba473f941a23cbee 69de40a4702df052c01e70f5079f8bd1f23a54be912d2b9a96b7891e381e6e3d usr/share/xray/lab/watchdog.uc
2d8cb3bfa773232056526f77c55dad30aa7c1271807507959d7c7f0f13573fc1 1e08944bbccaad76e92334ff0e3c997ee9f6fe1986edde4c0fafcd5b51d935df www/luci-static/resources/view/xray/dashboard_052.js
92705aa098c3709f1bc8293413a0892a48a607997605d60c34c1974fc6242c7f ba2d9a13fe56dd3a4e0502e81218fe40a864d211e8e4b72687cc3d40c04408db www/luci-static/resources/view/xray/lab_052.js
MANIFEST
base=https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/62092ff58302dff1fbc819d5e0f6fd17db660d4b/package/xtlsprovpn/files
while read -r old new path; do
    [ -f "/$path" ] && [ ! -L "/$path" ] || exit 1
    actual=$(sha256sum "/$path");actual=${actual%% *}
    [ "$actual" = "$old" ] || [ "$actual" = "$new" ] || {
        echo "Файл /$path отличается от проверенной версии. Установка отменена.";exit 1;
    }
    mkdir -p "$work/new/$(dirname "$path")"
    curl -q -4 --noproxy '*' -fL --connect-timeout 10 --max-time 60 "$base/$path" -o "$work/new/$path"
    printf '%s  %s\n' "$new" "$work/new/$path" | sha256sum -c -
done < "$work/manifest"
mkdir -p "$work/check"
cp /usr/share/xray/lab/* "$work/check/"
cp "$work/new/usr/share/xray/lab/"* "$work/check/"
ucode -c -o "$work/check.ucb" "$work/check/control.uc"
for path in etc/init.d/xray_core usr/bin/xray-lab usr/bin/xray-lab-control usr/bin/xray-lab-sync-safe;do
    sh -n "$work/new/$path"
done
mkdir -p /var/run/xray-lab-control
exec 9>/var/run/xray-lab-control/action.lock
flock -n 9 || { echo 'Операция приложения выполняется. Повторите после завершения.';exit 1; }
backup=$(mktemp -d /root/xtls-before-failopen.XXXXXX)
while read -r old new path; do
    mkdir -p "$backup/$(dirname "$path")"
    cp -p "/$path" "$backup/$path"
done < "$work/manifest"
if /etc/init.d/xray_lab_monitor running || /etc/init.d/xray_lab_monitor enabled;then monitor=1;fi
installing=1
/etc/init.d/xray_lab_monitor stop 8>&- 9>&-
while read -r old new path; do
    cp -p "/$path" "/$path.failopen-new"
    cat "$work/new/$path" > "/$path.failopen-new"
    mv "/$path.failopen-new" "/$path"
done < "$work/manifest"
if [ "$monitor" = 1 ];then /etc/init.d/xray_lab_monitor start 8>&- 9>&-;fi
installing=0
echo "Fail-open установлен. Резервная копия: $backup"
echo 'Перезапущен только монитор. Xray, NetBird и настройки подписки сохранены.'
