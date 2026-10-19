import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallLinks(unittest.TestCase):
    def run_script(self, mode, installed="absent", download="ok", checksum="ok",
                   platform="25.12.5", arch="aarch64"):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            release = d / "openwrt_release"
            release.write_text("DISTRIB_RELEASE='" + platform + "'\n")
            script = d / "run.sh"
            script.write_text((ROOT / (mode + ".sh")).read_text().replace(
                "/etc/openwrt_release", str(release)))
            bindir = d / "bin"
            bindir.mkdir()
            mock = """#!/bin/sh
printf '%s %s\\n' "${0##*/}" "$*" >> "$CALLS"
case "${0##*/}" in
id) echo 0 ;;
uname) echo "$ARCH" ;;
apk)
  if [ "$1" = info ]; then
    case "$3:$INSTALLED" in
      xtlsprovpn:absent) exit 1 ;;
      xtlsprovpn:*) exit 0 ;;
      'xtlsprovpn=1.2.0-r3:same'|'xtlsprovpn>1.2.0-r3:newer') exit 0 ;;
      *) exit 1 ;;
    esac
  fi ;;
curl)
  [ "$DOWNLOAD" = ok ] || exit 22
  while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then printf 'test APK' > "$2"; break; fi
    shift
  done ;;
sha256sum) cat >/dev/null; [ "$CHECKSUM" = ok ] ;;
esac
"""
            for name in ("apk", "curl", "sha256sum", "id", "uname"):
                path = bindir / name
                path.write_text(mock)
                path.chmod(0o700)
            calls = d / "calls"
            env = dict(os.environ, PATH=str(bindir) + ":" + os.environ["PATH"],
                       CALLS=str(calls), INSTALLED=installed, DOWNLOAD=download,
                       CHECKSUM=checksum, ARCH=arch)
            r = subprocess.run(["sh", str(script)], env=env,
                               capture_output=True, text=True)
            log = calls.read_text() if calls.exists() else ""
            packages = [line.split()[-1] for line in log.splitlines()
                        if line.startswith("curl ")]
            for package in packages:
                self.assertFalse(Path(package).parent.exists(), "temporary APK not removed")
            return r, log

    def test_fresh_install(self):
        r, log = self.run_script("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("apk add --allow-untrusted ", log)

    def test_upgrade_existing_package(self):
        r, log = self.run_script("update", "older")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("apk add --allow-untrusted ", log)
        self.assertNotIn("apk del", log)

    def test_wrong_mode_refused_before_changes(self):
        for mode, installed in (("install", "same"), ("update", "absent")):
            r, log = self.run_script(mode, installed)
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("apk update", log)

    def test_current_version_is_noop(self):
        r, log = self.run_script("update", "same")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Обновление не требуется", r.stdout)
        self.assertNotIn("apk update", log)

    def test_downgrade_refused(self):
        r, log = self.run_script("update", "newer")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("apk update", log)

    def test_failed_download_and_checksum_never_install(self):
        for download, checksum in (("error", "ok"), ("ok", "error")):
            r, log = self.run_script("update", "older", download, checksum)
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("apk add --allow-untrusted", log)

    def test_wrong_platform_refused(self):
        for release, arch in (("24.10.0", "aarch64"), ("25.12.5", "mips")):
            r, log = self.run_script("install", platform=release, arch=arch)
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("apk update", log)

    def test_scripts_only_differ_in_mode(self):
        self.assertEqual((ROOT / "install.sh").read_text().replace("MODE=install", "MODE=update"),
                         (ROOT / "update.sh").read_text())


if __name__ == "__main__":
    unittest.main()

