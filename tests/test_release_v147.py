"""Exercise publication failures before a release can become public."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_release_v141 import MOCK

ROOT = Path(__file__).resolve().parents[1]
APK = 'xtlsprovpn-1.4.7-r1.apk'
SERVER = 'xtls-router-bot-1.4.7.tar.gz'


class Publish147(unittest.TestCase):
    def test_only_valid_source_bound_bytes_become_public(self):
        for mode in ['ok', 'bad-manifest', 'bad-checksum', 'bad-upload', 'wrong-source', 'wrong-branch', 'wrong-target']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                bins = root/'bin'; bins.mkdir()
                (root/'scripts').symlink_to(ROOT/'scripts', target_is_directory=True)
                dist = root/'dist'; dist.mkdir()
                (dist/APK).write_bytes(b'isolated test package')
                subprocess.run(['python3', str(ROOT/'scripts/package-router-bot.py'), '--output', str(dist/SERVER)], check=True, stdout=subprocess.DEVNULL)
                subprocess.run(['python3', str(ROOT/'scripts/make-update-manifest.py'), str(dist/APK), '--output', str(dist/'update.json')], check=True)
                (dist/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  ./'+p.name+'\n' for p in [dist/APK, dist/SERVER]))
                if mode == 'bad-manifest':
                    m=json.loads((dist/'update.json').read_text());m['openwrt']=['25.12.5'];(dist/'update.json').write_text(json.dumps(m))
                if mode == 'bad-checksum':
                    (dist/APK).write_bytes(b'changed')
                source = 'a'*40
                if mode == 'wrong-target':
                    (root/'state.json').write_text(json.dumps({'isDraft':True,'targetCommitish':'b'*40}))
                gh=bins/'gh'; gh.write_text(MOCK); gh.chmod(0o755)
                git=bins/'git'; git.write_text('#!/bin/sh\necho '+('b'*40 if mode=='wrong-source' else source)+'\n');git.chmod(0o755)
                env=dict(os.environ, PATH=str(bins)+':'+os.environ['PATH'], GITHUB_REPOSITORY='djing1e/xtlsproVPN-for-OpenWRT',
                         GITHUB_SHA=source,GITHUB_REF='refs/heads/other' if mode=='wrong-branch' else 'refs/heads/main',
                         TEST_ROOT=str(root),TEST_MODE=mode,RUNNER_TEMP=str(root))
                result=subprocess.run(['bash',str(ROOT/'scripts/publish-v147.sh')],cwd=root,env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode==0,mode=='ok',result.stdout+result.stderr)
                calls=[json.loads(line) for line in (root/'calls').read_text().splitlines()] if (root/'calls').exists() else []
                self.assertEqual(any(c[:2]==['release','edit'] for c in calls), mode=='ok')


if __name__ == '__main__':
    unittest.main()
