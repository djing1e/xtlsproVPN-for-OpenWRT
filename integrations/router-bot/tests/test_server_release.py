import hashlib
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('server_release',ROOT/'scripts/package-router-bot.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class ServerReleaseTests(unittest.TestCase):
    def test_reproducible_archive_contains_all_public_helpers_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'a.tar.gz',Path(temp)/'b.tar.gz'
            p.package(a);p.package(b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with tarfile.open(a) as archive:
                prefix='xtls-router-bot-'+p.VERSION+'/'
                entries={m.name.removeprefix(prefix):m for m in archive.getmembers()}
                self.assertEqual(set(entries),set(p.DOCS)|{'server/'+v for v in p.SERVER}|{'VERSION','SHA256SUMS'})
                lines=archive.extractfile(entries['SHA256SUMS']).read().decode().splitlines()
                for line in lines:
                    digest,name=line.split()
                    self.assertEqual(digest,hashlib.sha256(archive.extractfile(entries[name]).read()).hexdigest())
                self.assertEqual(entries['server/upgrade-release.sh'].mode,0o755)
                self.assertFalse(any('token' in name or 'backup.key' in name or 'sqlite3' in name or '__pycache__' in name for name in entries))

if __name__=='__main__':unittest.main()
