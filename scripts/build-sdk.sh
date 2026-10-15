#!/usr/bin/env bash
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
work=${XT_BUILD_DIR:-"$project/.build"}
mkdir -p "$work"
name=openwrt-sdk-25.12.5-mediatek-filogic_gcc-14.3.0_musl.Linux-x86_64.tar.zst
expected=ff4a38a397caa2cfe1c39e18f84ddede14878221b3593c3f2c4cfe24e3ec4c25
if [ ! -d "$work/sdk" ];then
    curl --fail --location --retry 3 --connect-timeout 15 --max-time 900 \
        "https://downloads.openwrt.org/releases/25.12.5/targets/mediatek/filogic/$name" -o "$work/$name"
    printf '%s  %s\n' "$expected" "$work/$name" | sha256sum -c -
    mkdir "$work/sdk"
    tar --zstd -xf "$work/$name" -C "$work/sdk" --strip-components=1
fi
cd "$work/sdk"
./scripts/feeds update -a
./scripts/feeds install -a
mkdir -p package/xtlsprovpn
cp -R "$project/package/xtlsprovpn/." package/xtlsprovpn/
cat > .config <<'CONFIG'
CONFIG_ALL=n
CONFIG_ALL_KMODS=n
CONFIG_ALL_NONSHARED=n
CONFIG_PACKAGE_xtlsprovpn=m
CONFIG
make defconfig
make -j"${XT_BUILD_JOBS:-2}" package/xtlsprovpn/compile V=s
mkdir -p "$project/dist"
find bin -type f -name 'xtlsprovpn-*.apk' -exec cp '{}' "$project/dist/" \;
find "$project/dist" -type f -name '*.apk' -print -quit | grep -q .
(cd "$project/dist" && sha256sum ./*.apk > SHA256SUMS)
