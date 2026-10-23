#!/bin/sh
# Correct only the legacy firmware guard; retain architecture and manifest checks.
set -eu
umask 077
[ "$(id -u)" = 0 ] || { echo 'Запустите от root';exit 1; }
root=${FX_PACKAGE_COMPAT_ROOT:-}
file="$root/usr/bin/xray-lab-package"
[ -f "$file" ] && [ ! -L "$file" ] || exit 1
mkdir -p "$root/var/run/xray-lab-control"
exec 9>"$root/var/run/xray-lab-control/action.lock"
flock -n 9 || { echo 'Дождитесь завершения операции Xray';exit 1; }
work=$(mktemp "$file.compat.XXXXXX")
trap 'rm -f "$work"' EXIT
ucode - "$file" "$work" <<'UC'
let fs=require('fs'),body=fs.readfile(ARGV[0]);
const old='    [ "${DISTRIB_RELEASE:-}" = 25.12.5 ] && [ "$(uname -m)" = aarch64 ] || exit 1';
const next='    case "${DISTRIB_RELEASE:-}" in 25.12.5|25.12.6) ;; *) exit 1 ;; esac\n    [ "$(uname -m)" = aarch64 ] || exit 1';
if(index(body,old)<0) {
    if(index(body,next)>=0)exit(0);
    die('Неизвестная проверка платформы: файл не изменён');
}
if(length(split(body,old))!=2)die('Неоднозначная проверка платформы: файл не изменён');
body=replace(body,old,next);
body=replace(body,'OpenWrt 25.12.5 / aarch64.','OpenWrt 25.12.5/25.12.6 / aarch64.');
if(!fs.writefile(ARGV[1],body))die('Не удалось подготовить исправление');
UC
[ -s "$work" ] || { echo 'Поддержка 25.12.6 уже включена';exit 0; }
sh -n "$work"
backup=$(mktemp "$root/root/xray-package-before-25126.XXXXXX")
cp -p "$file" "$backup"
chmod 755 "$work"
mv "$work" "$file"
echo "Проверка версии исправлена. Резервная копия: $backup"
echo 'Повторите проверку обновлений в LuCI. Службы не перезапускались.'
