#!/usr/bin/env bash
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
work=${XT_BUILD_DIR:-"$project/.build"}
mkdir -p "$work"
name=openwrt-sdk-25.12.5-mediatek-filogic_gcc-14.3.0_musl.Linux-x86_64.tar.zst
expected=ff4a38a397caa2cfe1c39e18f84ddede14878221b3593c3f2c4cfe24e3ec4c25
if [ ! -d "$work/sdk" ];then
    url="https://downloads.openwrt.org/releases/25.12.5/targets/mediatek/filogic/$name"
    verified=0
    for attempt in 1 2 3 4 5;do
        if [ -f "$work/$name" ] && printf '%s  %s\n' "$expected" "$work/$name" | sha256sum -c - >/dev/null 2>&1;then
            verified=1;break
        fi
        echo "Downloading official SDK using HTTP/1.1, attempt $attempt (resume enabled)"
        curl --http1.1 --fail --silent --show-error --location --continue-at - \
            --connect-timeout 15 --max-time 900 --speed-limit 1024 --speed-time 45 \
            "$url" -o "$work/$name" || continue
        if printf '%s  %s\n' "$expected" "$work/$name" | sha256sum -c -;then verified=1;break;fi
        # A complete but mismatched archive must be downloaded again from zero.
        rm -f "$work/$name"
    done
    [ "$verified" = 1 ] || { echo 'SDK download/checksum failed after retries';exit 1; }
    mkdir "$work/sdk"
    tar --zstd -xf "$work/$name" -C "$work/sdk" --strip-components=1
fi
cd "$work/sdk"
./scripts/feeds update -a
./scripts/feeds install -a
mkdir -p package/xtlsprovpn
cp -R "$project/package/xtlsprovpn/." package/xtlsprovpn/
python3 "$project/scripts/stage-bot-bundle.py" "$work/sdk/package/xtlsprovpn/files/usr/share/xray/bot"
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
