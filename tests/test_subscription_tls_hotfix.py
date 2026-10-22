import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
SCRIPT=ROOT/'scripts/fix-subscription-tls-v142.sh'

class Hotfix(unittest.TestCase):
    def test_install_guards_idempotence_and_rollback(self):
        for scenario in ['ok','changed','bad-download','move-fail','wrong-version','symlink']:
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as temp:
                p=Path(temp);target=p/'router';tools=p/'tools';tools.mkdir();target.mkdir()
                source=SCRIPT.read_text();rows=source.split("<<'MANIFEST'\n",1)[1].split('\nMANIFEST',1)[0].splitlines()
                originals={}
                for row in rows:
                    rel,old,new,mode=row.split();file=target/rel;file.parent.mkdir(parents=True,exist_ok=True)
                    if old!='absent':
                        body=('original '+rel+'\n').encode();file.write_bytes(body);file.chmod(int(mode,8));originals[rel]=body
                        source=source.replace(old,hashlib.sha256(body).hexdigest())
                core=target/'etc/config/xray_core';core.parent.mkdir(parents=True);core.write_text('config canary')
                source=source.replace('TARGET_ROOT=/\n', 'TARGET_ROOT='+str(target)+'/\n')
                source=source.replace('/var/run/xray-lab-control',str(p/'run')).replace('/root/xtls-before-subscription-tls.',str(p/'backup.'))
                run=p/'fix.sh';run.write_text(source)
                (tools/'id').write_text('#!/bin/sh\necho 0\n')
                (tools/'apk').write_text('#!/bin/sh\necho xtlsprovpn-'+('1.4.1' if scenario=='wrong-version' else '1.4.2')+'-r1\n')
                (tools/'ucode').write_text('#!/bin/sh\nexit 0\n')
                (tools/'curl').write_text('''#!/usr/bin/env python3
import os,sys
from pathlib import Path
a=sys.argv[1:];url=next(x for x in a if x.startswith('https://'));rel=url.split('/files/',1)[1]
p=Path(os.environ['HOTFIX_TEMP'])
with (p/'downloads').open('a') as f:f.write(rel+'\\n')
body=(Path(os.environ['HOTFIX_SOURCE'])/rel).read_bytes()
if os.environ['HOTFIX_SCENARIO']=='bad-download' and rel.endswith('/main.uc'):body=b'corrupt'
Path(a[a.index('-o')+1]).write_bytes(body)
''')
                (tools/'mv').write_text('''#!/usr/bin/env python3
import os,sys
if os.environ['HOTFIX_SCENARIO']=='move-fail' and sys.argv[-1].endswith('/main.uc'):sys.exit(1)
os.execv('/bin/mv',['mv']+sys.argv[1:])
''')
                for t in tools.iterdir():t.chmod(0o755)
                main=target/'usr/lib/forkop-xray/main.uc'
                if scenario=='changed':main.write_text('custom changes')
                if scenario=='symlink':main.unlink();main.symlink_to(core)
                env=dict(os.environ,PATH=str(tools)+':'+os.environ['PATH'],HOTFIX_TEMP=str(p),HOTFIX_SOURCE=str(FILES),HOTFIX_SCENARIO=scenario)
                r=subprocess.run(['sh',str(run)],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(r.returncode==0,scenario=='ok',r.stdout+r.stderr)
                self.assertEqual(core.read_text(),'config canary')
                if scenario=='ok':
                    for row in rows:
                        rel,old,new,mode=row.split();self.assertEqual(hashlib.sha256((target/rel).read_bytes()).hexdigest(),new)
                    calls=(p/'downloads').read_text();again=subprocess.run(['sh',str(run)],env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(again.returncode,0,again.stderr);self.assertIn('already installed',again.stdout)
                    self.assertEqual((p/'downloads').read_text(),calls)
                else:
                    for rel,body in originals.items():
                        if scenario in ['changed','symlink'] and rel.endswith('/main.uc'):continue
                        self.assertEqual((target/rel).read_bytes(),body)
                    for row in rows:
                        rel,old,new,mode=row.split()
                        if old=='absent':self.assertFalse((target/rel).exists())

if __name__=='__main__':unittest.main()
