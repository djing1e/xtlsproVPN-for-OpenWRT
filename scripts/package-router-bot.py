#!/usr/bin/python3
"""Create a reproducible public server release; never include local secrets/state."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.4.2'
DOCS = ('README.md', 'ONBOARDING.md', 'EASY-ENROLLMENT.md', 'ADMIN-MENU.md', 'OPERATIONS.md', 'RECOVERY.md', 'DEVICE-UI-FIX.md', 'PRESENCE-RICH.md')
SERVER = ('backup.py', 'bot.py', 'connect.py', 'enroll_rescue.py', 'fleet.py', 'install-connect.py',
          'install-daily-backup.py', 'install-operator.py', 'install.py', 'operator_client.py',
          'operator_worker.py', 'upgrade.py', 'upgrade-release.sh', 'xtls-router-add',
          'xtls-router-bot-operator.path', 'xtls-router-bot-operator.service', 'xtls-router-bot.service',
          'setup-connect.sh', 'setup-operator.sh', 'setup-catalog.sh', 'setup-daily-backup.sh', 'setup-backup-password.sh', 'setup-device-ui.sh', 'setup-rich-presence.sh')


def package(output, root=ROOT):
    source = root/'integrations/router-bot'
    data = {}
    for name in (*DOCS, *('server/'+name for name in SERVER)):
        path = source/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError('Missing or unexpected public source: '+name)
        data[name] = path.read_bytes()
    data['VERSION'] = (VERSION+'\n').encode()
    data['SHA256SUMS'] = ''.join(hashlib.sha256(body).hexdigest()+'  '+name+'\n' for name,body in sorted(data.items())).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as stream, gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w') as archive:
        for name, body in sorted(data.items()):
            entry = tarfile.TarInfo('xtls-router-bot-'+VERSION+'/'+name)
            entry.size = len(body); entry.mtime = 0; entry.uid = entry.gid = 0
            entry.mode = 0o755 if name.endswith('.sh') or name=='server/xtls-router-add' else 0o644
            archive.addfile(entry, io.BytesIO(body))
    print(output.name, hashlib.sha256(output.read_bytes()).hexdigest(), output.stat().st_size)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    package(parser.parse_args().output)
