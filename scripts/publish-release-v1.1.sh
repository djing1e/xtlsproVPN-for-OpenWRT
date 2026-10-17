#!/usr/bin/env bash
# Promote the exact hardware-tested APK; never rebuild or relabel its contents.
set -euo pipefail
repo=${GITHUB_REPOSITORY:?}
release_commit=${GITHUB_SHA:?}
[[ "$repo" == djing1e/xtlsproVPN-for-OpenWRT ]] || exit 1
tag=v1.1.0
tested_commit=644bdfe43e7d43521f11540a01d1e5fdfc1b7a33
artifact_id=12100969800
archive_sha=c90d8deb50a25128ec6f9360a88aff0cedf9e954150d826b3471aa3594d34af3
apk_name=xtlsprovpn-1.1.0-r5.apk
apk_sha=eb9c3e45141409d1d2e5eaabfaff2012518c9a7f01a1c8daf89844dfc8bfd8d2
work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/xtls-release.XXXXXX")
trap 'rm -rf "$work"' EXIT

git diff --exit-code "$tested_commit" "$release_commit" -- package/xtlsprovpn
gh api "/repos/$repo/actions/artifacts/$artifact_id/zip" > "$work/artifact.zip"
printf '%s  %s\n' "$archive_sha" "$work/artifact.zip" | sha256sum -c -
mkdir "$work/assets" "$work/downloaded"
# The archive is SHA-pinned and contains precisely these two root-level files.
python3 - "$work/artifact.zip" "$work/assets" "$apk_name" <<'PY'
import sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    if sorted(z.namelist()) != sorted(['SHA256SUMS',sys.argv[3]]):
        raise SystemExit('Unexpected artifact entries')
    z.extractall(sys.argv[2])
PY
(cd "$work/assets" && sha256sum -c SHA256SUMS)
printf '%s  %s\n' "$apk_sha" "$work/assets/$apk_name" | sha256sum -c -

already_published=0
if gh release view "$tag" --repo "$repo" --json isDraft,targetCommitish > "$work/existing.json" 2> "$work/view-error"; then
    read -r is_draft target < <(python3 - "$work/existing.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));print(str(r['isDraft']).lower(),r['targetCommitish'])
PY
)
    if [[ "$is_draft" == false ]]; then
        already_published=1
    elif [[ "$target" != "$release_commit" ]]; then
        echo 'Existing draft targets another commit; refusing to replace it.' >&2
        exit 1
    fi
else
    gh release create "$tag" --repo "$repo" --draft --target "$release_commit" \
        --title 'xtlsproVPN v1.1.0' --notes-file docs/releases/v1.1.0.md
fi

if [[ "$already_published" == 0 ]]; then
    gh release upload "$tag" --repo "$repo" --clobber \
        "$work/assets/$apk_name" "$work/assets/SHA256SUMS"
fi
# Verify the uploaded assets before publishing a draft, or accept an identical rerun.
gh release download "$tag" --repo "$repo" --dir "$work/downloaded" \
    --pattern "$apk_name" --pattern SHA256SUMS
(cd "$work/downloaded" && sha256sum -c SHA256SUMS)
printf '%s  %s\n' "$apk_sha" "$work/downloaded/$apk_name" | sha256sum -c -
cmp "$work/assets/SHA256SUMS" "$work/downloaded/SHA256SUMS"
if [[ "$already_published" == 0 ]]; then
    gh release edit "$tag" --repo "$repo" --draft=false --latest
fi
gh release view "$tag" --repo "$repo" --json url,isDraft,tagName,assets
