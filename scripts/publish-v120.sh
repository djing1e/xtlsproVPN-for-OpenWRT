#!/usr/bin/env bash
# Promote the exact tested r3 artifact after successful build; never rebuild the APK.
set -euo pipefail
repo=${GITHUB_REPOSITORY:?}
[[ "$repo" == djing1e/xtlsproVPN-for-OpenWRT ]] || exit 1
run=39232522571
release_commit=b6f7ed179bd5069f075944d98c8b46debada69fd
tag=v1.2.0
apk_name=xtlsprovpn-1.2.0-r3.apk
work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/xtls-ui-release.XXXXXX")
trap 'rm -rf "$work"' EXIT

gh run watch "$run" --repo "$repo" --exit-status --interval 20
gh api "/repos/$repo/actions/runs/$run" > "$work/run.json"
gh api "/repos/$repo/actions/runs/$run/artifacts" > "$work/artifacts.json"
read -r artifact_id archive_sha < <(python3 - "$work/run.json" "$work/artifacts.json" "$release_commit" <<'PY'
import json,re,sys
r=json.load(open(sys.argv[1]));a=json.load(open(sys.argv[2]))['artifacts']
assert r['head_sha']==sys.argv[3] and r['conclusion']=='success' and r['status']=='completed'
a=[x for x in a if x['name']=='xtlsprovpn-1.2.0-openwrt-25.12.5-arm64']
assert len(a)==1 and not a[0]['expired'] and 0<a[0]['size_in_bytes']<2097152
digest=a[0]['digest'];assert re.fullmatch('sha256:[a-f0-9]{64}',digest)
print(a[0]['id'],digest[7:])
PY
)
[[ "$artifact_id" =~ ^[0-9]+$ && "$archive_sha" =~ ^[a-f0-9]{64}$ ]]
gh api "/repos/$repo/actions/artifacts/$artifact_id/zip" > "$work/artifact.zip"
printf '%s  %s\n' "$archive_sha" "$work/artifact.zip" | sha256sum -c -
mkdir "$work/assets" "$work/downloaded"
python3 - "$work/artifact.zip" "$work/assets" "$apk_name" <<'PY'
import hashlib,json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    assert sorted(z.namelist())==sorted(['SHA256SUMS','update.json',sys.argv[3]])
    assert sum(x.file_size for x in z.infolist())<10485760
    z.extractall(sys.argv[2])
    m=json.loads(z.read('update.json'));data=z.read(sys.argv[3]);sha=hashlib.sha256(data).hexdigest()
    assert m['schema']==1 and m['version']=='1.2.0-r3' and m['tag']=='v1.2.0'
    assert m['openwrt']==['25.12.5'] and m['architectures']==['aarch64']
    assert m['apk']=={'name':sys.argv[3],'size':len(data),'sha256':sha}
    assert z.read('SHA256SUMS').decode().strip()==sha+'  ./'+sys.argv[3]
PY
(cd "$work/assets" && sha256sum -c SHA256SUMS)

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
        --title 'xtlsproVPN v1.2.0 (r3)' --notes-file docs/releases/v1.2.0.md
fi
if [[ "$already_published" == 0 ]]; then
    gh release upload "$tag" --repo "$repo" --clobber \
        "$work/assets/$apk_name" "$work/assets/SHA256SUMS" "$work/assets/update.json"
fi
gh release download "$tag" --repo "$repo" --dir "$work/downloaded" \
    --pattern "$apk_name" --pattern SHA256SUMS --pattern update.json
for name in "$apk_name" SHA256SUMS update.json; do cmp "$work/assets/$name" "$work/downloaded/$name";done
(cd "$work/downloaded" && sha256sum -c SHA256SUMS)
if [[ "$already_published" == 0 ]]; then
    gh release edit "$tag" --repo "$repo" --draft=false --latest
fi
gh release view "$tag" --repo "$repo" --json url,isDraft,tagName,assets

