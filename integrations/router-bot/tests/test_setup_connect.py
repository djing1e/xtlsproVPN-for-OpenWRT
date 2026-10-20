import hashlib,re,subprocess,tempfile,unittest
from pathlib import Path

SERVER=Path(__file__).resolve().parents[1]/'server'

class SetupConnectTests(unittest.TestCase):
    def test_manifest_matches_reviewed_sources(self):
        source=(SERVER/'setup-connect.sh').read_text()
        entries=re.findall(r'^([a-f0-9]{64})  ([a-zA-Z0-9.-]+)$',source,re.M)
        self.assertEqual(len(entries),5)
        for digest,name in entries:
            self.assertEqual(hashlib.sha256((SERVER/name).read_bytes()).hexdigest(),digest)
        subprocess.run(['sh','-n',str(SERVER/'setup-connect.sh')],check=True)

    def test_operator_manifest_matches_reviewed_sources(self):
        source=(SERVER/'setup-operator.sh').read_text()
        entries=re.findall(r'^([a-f0-9]{64})  ([a-zA-Z0-9_.-]+)$',source,re.M)
        self.assertEqual(len(entries),10)
        for digest,name in entries:self.assertEqual(hashlib.sha256((SERVER/name).read_bytes()).hexdigest(),digest)
        subprocess.run(['sh','-n',str(SERVER/'setup-operator.sh')],check=True)

    def test_corrupt_download_stops_before_backup_or_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binpath=root/'bin';binpath.mkdir()
            config=root/'config';config.write_text('{}')
            backup=root/'backup.py';backup.write_text('')
            marker=root/'executed'
            mocks={'id':'echo 0', 'ssh-keyscan':'exit 0',
                'curl':'while [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then shift; printf CORRUPT > "$1"; exit 0; fi; shift; done; exit 1',
                'python3':f'touch "{marker}"; exit 0'}
            for name,body in mocks.items():
                path=binpath/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o755)
            script=(SERVER/'setup-connect.sh').read_text().replace('/etc/xtls-router-bot/config.json',str(config)).replace('/opt/xtls-router-bot/backup.py',str(backup))
            path=root/'setup.sh';path.write_text(script)
            result=subprocess.run(['sh',str(path)],env={'PATH':str(binpath)+':/usr/bin:/bin'},capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(marker.exists())
