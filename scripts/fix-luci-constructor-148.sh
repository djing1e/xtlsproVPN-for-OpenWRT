#!/bin/sh
# UI-only hotfix for the reviewed 1.4.8 files; no service or UCI changes.
set -eu
umask 077
[ "$(id -u)" = 0 ]
[ "$(apk info -v -e xtlsprovpn)" = xtlsprovpn-1.4.8-r1 ] || {
    echo 'Этот фикс предназначен для xtlsproVPN 1.4.8-r1.'; exit 1;
}
root=${FX_LUCI_FIX_ROOT:-}
work=$(mktemp -d /tmp/xtls-luci-fix.XXXXXX)
backup=
installing=0
cleanup() {
    rc=$?;trap - EXIT
    if [ "$rc" != 0 ] && [ "$installing" = 1 ]; then
        while read -r old new path; do
            cp -p "$backup/$path" "$root/$path.luci-new"
            mv -f "$root/$path.luci-new" "$root/$path"
        done < "$work/manifest"
        echo 'Предыдущие файлы интерфейса восстановлены.'
    fi
    rm -rf "$work"
    exit "$rc"
}
trap cleanup EXIT
cat > "$work/manifest" <<'MANIFEST'
fa96a5dfce8331b88784f7c0ab9f238a94815f957b46a936927445c0946bb166 9348374dabe502d1efb64d07f7e0514781bc2a9073b4ff825223491215c88c83 www/luci-static/resources/view/xray/lab_052.js
3dc68bd16cb02278b96d42e00f814354248b9deb6bfc9a959d56b6f749a19015 9c95feb88655b6bb5128d37dae493be68482cc3d3c54a35d67e0b13c4ce76805 www/luci-static/resources/view/xray/settings_memory147.js
c38888e382390f1f9f47f0594019f42f4de119fee4abf7ee1e590268ece3260a 9c95feb88655b6bb5128d37dae493be68482cc3d3c54a35d67e0b13c4ce76805 www/luci-static/resources/view/xray/settings_052.js
c38888e382390f1f9f47f0594019f42f4de119fee4abf7ee1e590268ece3260a 9c95feb88655b6bb5128d37dae493be68482cc3d3c54a35d67e0b13c4ce76805 www/luci-static/resources/view/xray/settings_transfer2.js
8405ca2952ec1632bb41c3a4c052492d6c350fe29a3ae47dd791c2edb5708b93 778cca9bb275d6ca782eb5dcf58d44d47b2bab465d12e58b9066fcae4df11402 www/luci-static/resources/view/xray/dashboard_052.js
3e0cd4020679ce1230462f1f72f3c6398697ac2554043a47da7618ad4c53bd42 eeedc947c0ec7322ebefbb4d3b5bccaa9b5633ffb7e64886d42eb9410b495467 www/luci-static/resources/view/xray/diagnostics_updates2.js
1c20fdfe4583c3b59be690bf73ed1d62c61cac05373ac9e38470223c118669fb 287f0ac85806c7c7426d5c0583d1e4b4879ce399ecaa69af7a2d0e2a439f19f9 www/luci-static/resources/view/xray/monitoring_compact_052.js
MANIFEST
changed=0
while read -r old new path; do
    [ -f "$root/$path" ] && [ ! -L "$root/$path" ] || exit 1
    actual=$(sha256sum "$root/$path");actual=${actual%% *}
    [ "$actual" = "$old" ] || [ "$actual" = "$new" ] || {
        echo "Файл /$path отличается от проверенной версии. Установка отменена.";exit 1;
    }
    [ "$actual" = "$new" ] || changed=1
done < "$work/manifest"
if [ "$changed" = 0 ];then echo 'Исправление уже установлено. Обновите LuCI через Ctrl+F5.';exit 0;fi
base=https://raw.githubusercontent.com/djing1e/xtlsproVPN-for-OpenWRT/3504579d3674b8cd55e4d55e885f16a41cf59ffe/package/xtlsprovpn/files
while read -r old new path; do
    mkdir -p "$work/new/$(dirname "$path")"
    curl -q -4 --noproxy '*' -fL --connect-timeout 10 --max-time 60 "$base/$path" -o "$work/new/$path"
    printf '%s  %s\n' "$new" "$work/new/$path" | sha256sum -c -
done < "$work/manifest"
backup=$(mktemp -d "$root/root/xtls-before-luci-constructor.XXXXXX")
while read -r old new path; do
    mkdir -p "$backup/$(dirname "$path")"
    cp -p "$root/$path" "$backup/$path"
done < "$work/manifest"
installing=1
while read -r old new path; do
    cp "$work/new/$path" "$root/$path.luci-new"
    chmod 644 "$root/$path.luci-new"
    mv -f "$root/$path.luci-new" "$root/$path"
done < "$work/manifest"
echo "Интерфейс исправлен. Резервная копия: $backup"
echo 'Службы и настройки не изменены. В браузере нажмите Ctrl+F5 и откройте «Настройки».'
