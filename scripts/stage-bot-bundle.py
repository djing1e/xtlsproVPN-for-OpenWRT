#!/usr/bin/python3
"""Stage only canonical public router code into the SDK package tree."""
import argparse
import hashlib
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
FILES=('ssh.uc','ssh-entry','admin.uc','admin-worker','updates.uc','update-worker','onboard.uc','onboard.sh','install.sh','refresh.sh','join.sh','enable-wrapper-guard.sh')


def stage(destination):
    if not destination.as_posix().endswith('/package/xtlsprovpn/files/usr/share/xray/bot') or destination.is_symlink():
        raise ValueError('Expected an SDK package staging destination')
    source=ROOT/'integrations/router-bot/router'
    if destination.exists():shutil.rmtree(destination)
    destination.mkdir(parents=True)
    sums=[]
    for name in FILES:
        path=source/name
        if not path.is_file() or path.is_symlink():raise ValueError('Missing canonical helper: '+name)
        content=path.read_bytes()
        if len(content)>100000:raise ValueError('Unexpected helper size')
        target=destination/name;target.write_bytes(content);target.chmod(0o644)
        sums.append(hashlib.sha256(content).hexdigest()+'  '+name)
    (destination/'bundle.sha256').write_text('\n'.join(sums)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path);args=parser.parse_args();stage(args.destination)
