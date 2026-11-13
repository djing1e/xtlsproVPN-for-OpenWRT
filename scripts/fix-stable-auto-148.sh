#!/bin/sh
# Reviewed 1.4.8 runtime/UI patch; no UCI, Xray restart or firewall reload.
set -eu
umask 077
[ "$(id -u)" = 0 ]
[ "$(apk info -v -e xtlsprovpn)" = xtlsprovpn-1.4.8-r1 ] || {
    echo 'Этот фикс предназначен для xtlsproVPN 1.4.8-r1.';exit 1;
}
root=${FX_STABLE_AUTO_ROOT:-}
work=$(mktemp -d /tmp/xtls-stable-auto.XXXXXX)
backup=
installing=0
monitor_stopped=0
cleanup() {
    rc=$?;trap - EXIT
    if [ "$rc" != 0 ] && [ "$installing" = 1 ];then
        while read -r old alt new path;do
            if [ -f "$backup/$path" ];then
                cp -p "$backup/$path" "$root/$path.auto-new"
                mv -f "$root/$path.auto-new" "$root/$path"
            else
                rm -f "$root/$path" "$root/$path.auto-new"
            fi
        done < "$work/manifest"
        echo 'Предыдущий код восстановлен.'
    fi
    if [ "$monitor_stopped" = 1 ];then "$root/etc/init.d/xray_lab_monitor" start || :;fi
    rm -rf "$work"
    exit "$rc"
}
trap cleanup EXIT
cat > "$work/manifest" <<'MANIFEST'
8039f53b4d31e5ed8c6bc355b2f9ecc2d60172b53a0588062a3185acbad30ce2 8039f53b4d31e5ed8c6bc355b2f9ecc2d60172b53a0588062a3185acbad30ce2 ff843939ca3ed7239f1a5a261890d565d8820d35865367a58a3fb8e193564558 usr/bin/xray-lab-control
- - f660d68cd0d53a18375f91d749bd1475589d1a2190b69867c1e9157fdcc5363c usr/share/xray/lab/auto_policy.mjs
- - 14bd9e78b8a2b32c804461c9fd0b1cbf85bbf26ec0ebfd58b53adddaf058c477 usr/share/xray/lab/auto_runtime.mjs
- - ec88cb5d41c8b8ef4e3adaf01cab799110b8bd30e7078a939e069c24eea20278 usr/share/xray/lab/auto_select.uc
4f235942f851fd6654fa7640f1ef6d7343a2f7561c2e1eaa5f458518593dceb9 4f235942f851fd6654fa7640f1ef6d7343a2f7561c2e1eaa5f458518593dceb9 c0ec672fce721a2cc86188c76da6cdc35cb3bf246b823507977afc87f613ee0c usr/share/xray/lab/control.uc
78f7d9e216fa6992caf423245a0ae72ebda2fff98f0a9562ddb3e33e7128c74c 78f7d9e216fa6992caf423245a0ae72ebda2fff98f0a9562ddb3e33e7128c74c 8c7c65c37bcc9958c380eec60f4ed0e58bce02922d10340da4a8659919d36ad5 usr/share/xray/lab/select_live.uc
23212498f7578d11c65a8ad602fce22f9d11ffdf1e9378dc96531ae4234c717f 23212498f7578d11c65a8ad602fce22f9d11ffdf1e9378dc96531ae4234c717f c808d565fb4c2b3579165bb2c895bd2618f7ff0ae783f1f459766302c4174c49 usr/share/xray/lab/state.mjs
69de40a4702df052c01e70f5079f8bd1f23a54be912d2b9a96b7891e381e6e3d 69de40a4702df052c01e70f5079f8bd1f23a54be912d2b9a96b7891e381e6e3d 7b5a313d4966f19db623cf5867d9346eb4f334f81c1c943fdcd69c268cee3b29 usr/share/xray/lab/watchdog.uc
c30c81a4e71e1320de5ec66e4b328dc0b373160134ce16944d25da5d8969c95e c30c81a4e71e1320de5ec66e4b328dc0b373160134ce16944d25da5d8969c95e 394beb428874ff89c4fbc5059b2466e30ca019f2d3cc56d442fc9f9c626a70ca usr/share/xray/lab_prepare.uc
287f0ac85806c7c7426d5c0583d1e4b4879ce399ecaa69af7a2d0e2a439f19f9 287f0ac85806c7c7426d5c0583d1e4b4879ce399ecaa69af7a2d0e2a439f19f9 7fbfc5c553204debf21faa265a4cb79f7a376d553712a45f15d3af28f7909215 www/luci-static/resources/view/xray/monitoring_148.js
287f0ac85806c7c7426d5c0583d1e4b4879ce399ecaa69af7a2d0e2a439f19f9 1c20fdfe4583c3b59be690bf73ed1d62c61cac05373ac9e38470223c118669fb 7fbfc5c553204debf21faa265a4cb79f7a376d553712a45f15d3af28f7909215 www/luci-static/resources/view/xray/monitoring_compact_052.js
9c95feb88655b6bb5128d37dae493be68482cc3d3c54a35d67e0b13c4ce76805 c38888e382390f1f9f47f0594019f42f4de119fee4abf7ee1e590268ece3260a a9c0461eb1d8d5b70455b033fe117137285f49b73157bb763c9a18cdd98c66ef www/luci-static/resources/view/xray/settings_052.js
9c95feb88655b6bb5128d37dae493be68482cc3d3c54a35d67e0b13c4ce76805 3dc68bd16cb02278b96d42e00f814354248b9deb6bfc9a959d56b6f749a19015 a9c0461eb1d8d5b70455b033fe117137285f49b73157bb763c9a18cdd98c66ef www/luci-static/resources/view/xray/settings_memory147.js
9c95feb88655b6bb5128d37dae493be68482cc3d3c54a35d67e0b13c4ce76805 c38888e382390f1f9f47f0594019f42f4de119fee4abf7ee1e590268ece3260a a9c0461eb1d8d5b70455b033fe117137285f49b73157bb763c9a18cdd98c66ef www/luci-static/resources/view/xray/settings_transfer2.js
MANIFEST
changed=0
while read -r old alt new path;do
    if [ ! -e "$root/$path" ] && [ ! -L "$root/$path" ] && [ "$old" = - ];then changed=1;continue;fi
    [ -f "$root/$path" ] && [ ! -L "$root/$path" ] || exit 1
    actual=$(sha256sum "$root/$path");actual=${actual%% *}
    [ "$actual" = "$old" ] || [ "$actual" = "$alt" ] || [ "$actual" = "$new" ] || {
        echo "Файл /$path отличается от проверенной версии. Установка отменена.";exit 1;
    }
    [ "$actual" = "$new" ] || changed=1
done < "$work/manifest"
if [ "$changed" = 0 ];then echo 'Стабильный автовыбор уже установлен.';exit 0;fi
base=https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/5f028d15b40ac0043168ba1ab7550528b89050cb/package/xtlsprovpn/files
while read -r old alt new path;do
    mkdir -p "$work/new/$(dirname "$path")"
    curl -q -4 --noproxy '*' -fL --connect-timeout 10 --max-time 60 "$base/$path" -o "$work/new/$path"
    printf '%s  %s\n' "$new" "$work/new/$path" | sha256sum -c -
done < "$work/manifest"
mkdir -p "$work/check"
cp "$root/usr/share/xray/lab/"* "$work/check/"
cp "$work/new/usr/share/xray/lab/"* "$work/check/"
ucode -c -o "$work/control.ucb" "$work/check/control.uc"
ucode -c -o "$work/auto.ucb" "$work/check/auto_select.uc"
sh -n "$work/new/usr/bin/xray-lab-control"
mkdir -p "$root/var/run/xray-lab-control"
exec 9>"$root/var/run/xray-lab-control/action.lock"
flock -n 9 || { echo 'Дождитесь завершения операции роутера и повторите установку.';exit 1; }
backup=$(mktemp -d "$root/root/xtls-before-stable-auto.XXXXXX")
while read -r old alt new path;do
    if [ -f "$root/$path" ];then mkdir -p "$backup/$(dirname "$path")";cp -p "$root/$path" "$backup/$path";fi
done < "$work/manifest"
if "$root/etc/init.d/xray_lab_monitor" running >/dev/null 2>&1;then
    monitor_stopped=1
    "$root/etc/init.d/xray_lab_monitor" stop
fi
installing=1
while read -r old alt new path;do
    mkdir -p "$root/$(dirname "$path")"
    cp "$work/new/$path" "$root/$path.auto-new"
    case "$path" in usr/bin/*) chmod 755 "$root/$path.auto-new";; *) chmod 644 "$root/$path.auto-new";; esac
    mv -f "$root/$path.auto-new" "$root/$path"
done < "$work/manifest"
if [ "$monitor_stopped" = 1 ];then "$root/etc/init.d/xray_lab_monitor" start;monitor_stopped=0;fi
installing=0
echo "Стабильный автовыбор установлен. Резервная копия: $backup"
echo 'Перезапущен только работавший монитор. Xray, DNS, firewall и настройки сохранены.'
echo 'Проверка маршрута: 10 с по умолчанию; фоновые замеры сохраняют прежний интервал.'
echo 'Для работы требуется включённый мониторинг. Обновите LuCI через Ctrl+F5.'
