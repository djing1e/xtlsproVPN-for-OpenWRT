import os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
SCRIPT=ROOT/'scripts/fix-stable-auto-148.sh'

class StableAutoInstaller(unittest.TestCase):
    def test_transaction_repeat_corruption_unknown_lock_and_rollback(self):
        rows=SCRIPT.read_text().split("<<'MANIFEST'\n",1)[1].split('\nMANIFEST',1)[0].splitlines()
        entries=[line.split() for line in rows]
        for case in ('success','inactive','unknown','corrupt','locked','rollback'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                r=Path(temp);(r/'root').mkdir();(r/'bin').mkdir();(r/'etc/init.d').mkdir(parents=True)
                for old,alt,new,path in entries:
                    if old=='-':continue
                    target=r/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(FILES/path,target)
                if case=='unknown':(r/'usr/share/xray/lab/state.mjs').write_text('custom code')
                before={path:(r/path).read_bytes() for _,_,_,path in entries if (r/path).exists()}
                def exe(name,body):
                    p=r/'bin'/name;p.write_text('#!/usr/bin/env python3\n'+body);p.chmod(0o755)
                exe('id',"print('0')\n");exe('apk',"print('xtlsprovpn-1.4.8-r1')\n");exe('ucode','')
                if case=='locked':exe('flock','raise SystemExit(1)\n')
                exe('curl',f'''import pathlib,sys
args=sys.argv[1:];url=next(x for x in args if x.startswith('https://'))
source=pathlib.Path({str(FILES)!r})/url.split('/package/xtlsprovpn/files/',1)[1]
pathlib.Path(args[args.index('-o')+1]).write_bytes(b'corrupt' if {case=='corrupt'!r} else source.read_bytes())
''')
                monitor=r/'etc/init.d/xray_lab_monitor';monitor.write_text(f'''#!/bin/sh
echo "$1" >> '{r}/monitor-calls'
if [ "$1" = running ];then exit {1 if case=='inactive' else 0};fi
exit 0
''');monitor.chmod(0o755)
                if case=='rollback':
                    (r/'fail-once').touch()
                    exe('mv',f'''import os,pathlib,sys
args=[a for a in sys.argv[1:] if a!='-f'];marker=pathlib.Path({str(r/'fail-once')!r})
if args[-1].endswith('/auto_runtime.mjs') and marker.exists():marker.unlink();sys.exit(1)
os.replace(*args)
''')
                env=dict(os.environ,FX_STABLE_AUTO_ROOT=str(r),PATH=str(r/'bin')+':'+os.environ['PATH'])
                result=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode==0,case in ('success','inactive'),result.stdout+result.stderr)
                after={path:(r/path).read_bytes() for _,_,_,path in entries if (r/path).exists()}
                calls=(r/'monitor-calls').read_text().splitlines() if (r/'monitor-calls').exists() else []
                if case in ('success','inactive'):
                    self.assertEqual(after,{path:(FILES/path).read_bytes() for _,_,_,path in entries})
                    self.assertEqual(calls,['running','stop','start'] if case=='success' else ['running'])
                    again=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=5)
                    self.assertEqual(again.returncode,0,again.stderr)
                    self.assertEqual(len(list((r/'root').iterdir())),1)
                else:
                    self.assertEqual(before,after)
                    self.assertEqual(calls,['running','stop','start'] if case=='rollback' else [])
                self.assertFalse(list(r.rglob('*.auto-new')))

if __name__=='__main__':unittest.main()
