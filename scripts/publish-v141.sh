#!/usr/bin/env bash
# Publish exact source-bound artifacts from the successful official SDK run.
set -euo pipefail
repo=${GITHUB_REPOSITORY:?}
[[ "$repo" == djing1e/xtlsproVPN-for-OpenWRT ]] || exit 1
run=39462485426
source_commit=f4e7b0e67ae17549a6f42232b73295e52a68dd03
release_commit=$(git rev-parse HEAD)
git diff --exit-code "$source_commit" "$release_commit" -- package/xtlsprovpn integrations/router-bot scripts/stage-bot-bundle.py scripts/build-sdk.sh scripts/package-router-bot.py
tag=v1.4.1
apk_name=xtlsprovpn-1.4.1-r1.apk
server_name=xtls-router-bot-1.4.1.tar.gz
work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/xtls-release-141.XXXXXX")
trap 'rm -rf "$work"' EXIT

gh run watch "$run" --repo "$repo" --exit-status --interval 20
gh api "/repos/$repo/actions/runs/$run" > "$work/run.json"
gh api "/repos/$repo/actions/runs/$run/artifacts" > "$work/artifacts.json"
read -r artifact_id archive_sha < <(python3 - "$work/run.json" "$work/artifacts.json" "$source_commit" <<'PY'
import json,re,sys
r=json.load(open(sys.argv[1])); artifacts=json.load(open(sys.argv[2]))['artifacts']
assert r['head_sha']==sys.argv[3] and r['conclusion']=='success' and r['status']=='completed'
a=[x for x in artifacts if x['name']=='xtlsprovpn-1.4.1-openwrt-25.12.5-arm64']
assert len(a)==1 and not a[0]['expired'] and 0<a[0]['size_in_bytes']<2097152
assert re.fullmatch('sha256:[a-f0-9]{64}',a[0]['digest'])
assert a[0]['digest']=='sha256:53703db79807b8be0dabaf112d9206c5fe68d8f09f4f711076906b12328356ed'
print(a[0]['id'],a[0]['digest'][7:])
PY
)
[[ "$artifact_id" =~ ^[0-9]+$ && "$archive_sha" =~ ^[a-f0-9]{64}$ ]]
gh api "/repos/$repo/actions/artifacts/$artifact_id/zip" > "$work/artifact.zip"
printf '%s  %s\n' "$archive_sha" "$work/artifact.zip" | sha256sum -c -
mkdir "$work/assets" "$work/downloaded"
python3 - "$work/artifact.zip" "$work/assets" "$apk_name" "$server_name" <<'PY'
import hashlib,json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    apk,server=sys.argv[3:5]
    assert sorted(z.namelist())==sorted(['SHA256SUMS','update.json',apk,server])
    assert sum(x.file_size for x in z.infolist())<16777216
    m=json.loads(z.read('update.json')); data=z.read(apk); sha=hashlib.sha256(data).hexdigest()
    assert sha=='8f3e211fd58160938786c981469d66ce5bed8b1e3195ab25d00f02df56c00c55' and len(data)==184891
    assert m['schema']==1 and m['version']=='1.4.1-r1' and m['tag']=='v1.4.1'
    assert m['openwrt']==['25.12.5'] and m['architectures']==['aarch64']
    assert m['apk']=={'name':apk,'size':len(data),'sha256':sha}
    expected={sha+'  ./'+apk,hashlib.sha256(z.read(server)).hexdigest()+'  ./'+server}
    assert set(z.read('SHA256SUMS').decode().splitlines())==expected
    assert len(z.read(server))<4194304
    z.extractall(sys.argv[2])
    print(json.dumps(m,sort_keys=True))
    print('SERVER_SHA256='+hashlib.sha256(z.read(server)).hexdigest())
    print('ARTIFACT_SERVER_BYTES='+str(len(z.read(server))))
PY
(cd "$work/assets" && sha256sum -c SHA256SUMS)
python3 scripts/package-router-bot.py --output "$work/rebuilt-server.tar.gz"
cmp "$work/rebuilt-server.tar.gz" "$work/assets/$server_name"

# Branch runs verify and print metadata, but never create or publish releases.
if [[ "${PUBLISH_RELEASE:-false}" != true ]]; then
    echo 'Release assets verified; publication disabled for this run.'
    exit 0
fi
already_published=0
if gh release view "$tag" --repo "$repo" --json isDraft,targetCommitish > "$work/existing.json" 2>/dev/null; then
    read -r draft target < <(python3 - "$work/existing.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));print(str(r['isDraft']).lower(),r['targetCommitish'])
PY
)
    [[ "$target" == "$release_commit" ]] || { echo 'Release targets another commit';exit 1; }
    [[ "$draft" != false ]] || already_published=1
else
    gh release create "$tag" --repo "$repo" --draft --target "$release_commit" \
        --title 'xtlsproVPN v1.4.1 (r1) · cumulative router and bot release' --notes-file docs/releases/v1.4.1.md
fi
if [[ "$already_published" == 0 ]]; then
    gh release upload "$tag" --repo "$repo" --clobber \
        "$work/assets/$apk_name" "$work/assets/$server_name" "$work/assets/SHA256SUMS" "$work/assets/update.json"
fi
gh release download "$tag" --repo "$repo" --dir "$work/downloaded" \
    --pattern "$apk_name" --pattern "$server_name" --pattern SHA256SUMS --pattern update.json
for name in "$apk_name" "$server_name" SHA256SUMS update.json; do cmp "$work/assets/$name" "$work/downloaded/$name";done
(cd "$work/downloaded" && sha256sum -c SHA256SUMS)
if [[ "$already_published" == 0 ]]; then
    gh release edit "$tag" --repo "$repo" --draft=false --latest
fi
gh release view "$tag" --repo "$repo" --json url,isDraft,tagName,assets
