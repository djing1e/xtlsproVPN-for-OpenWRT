#!/usr/bin/env bash
# Inputs come only from the successful SDK build in the same Actions run.
set -euo pipefail
repo=${GITHUB_REPOSITORY:?}
source_commit=${GITHUB_SHA:?}
[[ "$repo" == djing1e/xtlsproVPN-for-OpenWRT ]]
[[ "${GITHUB_REF:-}" == refs/heads/main ]]
[[ "$(git rev-parse HEAD)" == "$source_commit" ]]
apk_name=xtlsprovpn-1.4.8-r1.apk
server_name=xtls-router-bot-1.4.8.tar.gz
tag=v1.4.8
work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/xtls-release-148.XXXXXX")
trap 'rm -rf "$work"' EXIT
python3 - <<'PY'
import hashlib,json
from pathlib import Path
p=Path('dist'); apk=p/'xtlsprovpn-1.4.8-r1.apk'; server=p/'xtls-router-bot-1.4.8.tar.gz'
assert sorted(x.name for x in p.iterdir())==sorted([apk.name,server.name,'SHA256SUMS','update.json'])
m=json.loads((p/'update.json').read_text()); data=apk.read_bytes()
assert 0<len(data)<8388608 and 0<server.stat().st_size<4194304
assert m['schema']==1 and m['tag']=='v1.4.8' and m['version']=='1.4.8-r1'
assert m['openwrt']==['25.12.5','25.12.6'] and m['architectures']==['aarch64']
assert 1024<=m['installed_size_kb']<=32768
assert m['apk']==dict(name=apk.name,size=len(data),sha256=hashlib.sha256(data).hexdigest())
expected={hashlib.sha256(x.read_bytes()).hexdigest()+'  ./'+x.name for x in (apk,server)}
assert set((p/'SHA256SUMS').read_text().splitlines())==expected
PY
(cd dist && sha256sum -c SHA256SUMS)
python3 scripts/package-router-bot.py --output "$work/rebuilt-server.tar.gz"
cmp "$work/rebuilt-server.tar.gz" "dist/$server_name"
published=0
if gh release view "$tag" --repo "$repo" --json isDraft,targetCommitish > "$work/release.json" 2>/dev/null; then
    read -r draft target < <(python3 - "$work/release.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); print(str(r['isDraft']).lower(),r['targetCommitish'])
PY
)
    [[ "$target" == "$source_commit" ]] || { echo 'Release targets another source commit';exit 1; }
    [[ "$draft" != false ]] || published=1
else
    gh release create "$tag" --repo "$repo" --draft --target "$source_commit" \
        --title 'xtlsproVPN v1.4.8 (r1) · Direct Internet fallback and safe subscription recovery' --notes-file docs/releases/v1.4.8.md
fi
if [[ "$published" == 0 ]]; then
    gh release upload "$tag" --repo "$repo" --clobber \
        "dist/$apk_name" "dist/$server_name" dist/SHA256SUMS dist/update.json
fi
mkdir "$work/downloaded"
gh release download "$tag" --repo "$repo" --dir "$work/downloaded" \
    --pattern "$apk_name" --pattern "$server_name" --pattern SHA256SUMS --pattern update.json
for name in "$apk_name" "$server_name" SHA256SUMS update.json; do
    cmp "dist/$name" "$work/downloaded/$name"
done
(cd "$work/downloaded" && sha256sum -c SHA256SUMS)
if [[ "$published" == 0 ]]; then
    gh release edit "$tag" --repo "$repo" --draft=false --latest
fi
gh release view "$tag" --repo "$repo" --json url,isDraft,tagName,assets
