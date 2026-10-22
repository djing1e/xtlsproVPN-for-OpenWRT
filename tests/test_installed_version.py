import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

LIB = Path(__file__).resolve().parents[1] / 'package/xtlsprovpn/files/usr/share/xray/lab'

@unittest.skipUnless(shutil.which('ucode'), 'ucode runtime required')
class InstalledVersion(unittest.TestCase):
    def test_database_version_is_shared_and_read_again_after_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            apk = root / 'apk'
            apk.write_text('#!/bin/sh\n[ "$*" = "info -v -e xtlsprovpn" ] || exit 99\ncat "$VERSION_FIXTURE"\nexit "${VERSION_RC:-0}"\n')
            apk.chmod(0o755)
            fixture = root / 'version'
            fixture.write_text('xtlsprovpn-1.4.1-r1\n')
            script = root / 'test.uc'
            script.write_text("import * as fs from 'fs'; import { installed_version } from '" + str(LIB/'package_release.mjs') + "'; let a=installed_version(); fs.writefile(getenv('VERSION_FIXTURE'),'xtlsprovpn-1.4.2-r1\\n'); printf('%J',[a,installed_version()]);")
            env = dict(os.environ, PATH=str(root)+':'+os.environ['PATH'], VERSION_FIXTURE=str(fixture))
            result = subprocess.run(['ucode', str(script)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['1.4.1-r1', '1.4.2-r1'])
            script.write_text("import { installed_version } from '" + str(LIB/'package_release.mjs') + "'; printf('%J',installed_version());")
            for text, rc in [('xtlsprovpn-1.4.0-r1\n', '1'), ('bad output\n', '0'), ('xtlsprovpn-1.4.1-r1 description:\n', '0')]:
                fixture.write_text(text)
                result = subprocess.run(['ucode',str(script)], capture_output=True,text=True,env=dict(env,VERSION_RC=rc))
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIsNone(json.loads(result.stdout))
        self.assertIn('version:installed_version()', (LIB/'state.mjs').read_text())
        self.assertIn('installed_version as installed', (LIB/'package_update.uc').read_text())
