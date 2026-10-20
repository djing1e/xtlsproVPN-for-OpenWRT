#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || { echo 'Запусти подготовку от root на роутере.';exit 1; }
[ "$#" = 1 ] || { echo 'Usage: xray-lab-bot prepare PROFILE.json';exit 1; }
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
stage=$(mktemp -d /tmp/xtls-bot-onboard.XXXXXX)
trap 'rm -rf "$stage"' EXIT
ucode "$base/onboard.uc" profile-key "$1" > "$stage/bot.pub"
# Validate an existing binding before touching authorization or helper files.
if [ -f /etc/xtlspro-bot/profile.json ]; then ucode "$base/onboard.uc" prepare "$1" > /dev/null;fi
sh "$base/install.sh" "$stage/bot.pub"
mkdir -p /etc/xtlspro-rescue
chmod 700 /etc/xtlspro-rescue
if [ ! -f /etc/xtlspro-rescue/id_ed25519 ]; then
    dropbearkey -t ed25519 -f /etc/xtlspro-rescue/id_ed25519 > /dev/null
fi
chmod 600 /etc/xtlspro-rescue/id_ed25519
ucode "$base/onboard.uc" prepare "$1" > /dev/null
ucode "$base/onboard.uc" passport > /root/xtls-router-passport.json
chmod 600 /root/xtls-router-passport.json
printf '\nКод подключения (только публичные данные):\nxtls-enroll-v1:'
base64 /root/xtls-router-passport.json | tr -d '\n'
printf '\n\nПаспорт: /root/xtls-router-passport.json\n'
