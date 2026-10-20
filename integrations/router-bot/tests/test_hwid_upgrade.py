import hashlib,os,subprocess,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]

class HwidUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.dest=self.root/'private';self.dest.mkdir();self.bundle=self.root/'bundle';self.bundle.mkdir()
        (self.dest/'profile.json').write_text('{}');(self.dest/'ssh.uc').write_text('old private')
        (self.bundle/'ssh.uc').write_text('old bundle')
        (self.bundle/'bundle.sha256').write_text(hashlib.sha256(b'old bundle').hexdigest()+'  ssh.uc\n')
        self.before={p:p.read_bytes() for p in [self.dest/'ssh.uc',self.bundle/'ssh.uc',self.bundle/'bundle.sha256']}
        self.bins=self.root/'bin';self.bins.mkdir()
        self.payload=self.root/'payload';self.payload.write_bytes((BASE/'router/ssh.uc').read_bytes())
        for name,body in [('id','echo 0'),('ucode','exit 0'),('curl','while [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then shift; cp "$HWID_PAYLOAD" "$1"; exit 0; fi; shift; done; exit 1')]:
            path=self.bins/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o755)
        src=(BASE/'router/upgrade-hwid.sh').read_text().replace('/etc/xtlspro-bot',str(self.dest)).replace('/usr/share/xray/bot',str(self.bundle)).replace('/root/xtls-before-hwid-bridge.',str(self.root/'backup.'))
        for item in ['xtlspro-bot-admin','xtlspro-netbird','xray-lab-control']:
            directory=self.root/item;directory.mkdir();src=src.replace('/var/run/'+item,str(directory))
        self.script=self.root/'upgrade.sh';self.script.write_text(src)
        self.env=dict(os.environ,PATH=str(self.bins)+':'+os.environ['PATH'],HWID_PAYLOAD=str(self.payload))
    def call(self):return subprocess.run(['sh',str(self.script)],env=self.env,capture_output=True,text=True,timeout=10)
    def test_bridge_and_bundle_updated_together_without_settings_mutation(self):
        value=self.call();self.assertEqual(value.returncode,0,value.stdout+value.stderr)
        self.assertEqual((self.dest/'ssh.uc').read_bytes(),self.payload.read_bytes())
        self.assertEqual((self.bundle/'ssh.uc').read_bytes(),self.payload.read_bytes())
        self.assertEqual((self.dest/'profile.json').read_text(),'{}')
        self.assertEqual((self.dest/'ssh.uc').stat().st_mode&0o777,0o600)
        subprocess.run(['sha256sum','-c','bundle.sha256'],cwd=self.bundle,check=True,capture_output=True)
    def test_corrupt_download_leaves_private_and_bundle_unchanged(self):
        self.payload.write_text('corrupt')
        self.assertNotEqual(self.call().returncode,0)
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
    def test_partial_install_rolls_back_private_bundle_and_manifest(self):
        path=self.bins/'mv';path.write_text('#!/bin/sh\nif [ "$2" = "'+str(self.dest/'ssh.uc')+'" ]; then exit 1; fi\nexec /usr/bin/mv "$@"\n');path.chmod(0o755)
        self.assertNotEqual(self.call().returncode,0)
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
