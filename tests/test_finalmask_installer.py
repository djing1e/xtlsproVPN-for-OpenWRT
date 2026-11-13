import os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/fix-finalmask-148.sh'
CURRENT=ROOT/'package/xtlsprovpn/files/usr/lib/forkop-xray/parser.uc'
OLD=ROOT/'tests/fixtures/finalmask-148/parser.uc'

@unittest.skipUnless(shutil.which('ucode'),'ucode required for compile gate')
class FinalMaskInstaller(unittest.TestCase):
    def test_transaction_integrity_repeat_lock_and_concurrent_change(self):
        for case in ('success','version','custom','corrupt','busy','concurrent','rollback'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                r=Path(temp);(r/'bin').mkdir();(r/'root').mkdir()
                target=r/'usr/lib/forkop-xray/parser.uc';target.parent.mkdir(parents=True)
                target.write_bytes(b'custom code' if case=='custom' else OLD.read_bytes());before=target.read_bytes()
                def exe(name,body):
                    p=r/'bin'/name;p.write_text('#!/usr/bin/env python3\n'+body);p.chmod(0o755)
                exe('id',"print('0')\n")
                exe('apk',"print("+repr('xtlsprovpn-1.4.7-r1' if case=='version' else 'xtlsprovpn-1.4.8-r1')+")\n")
                if case=='busy':exe('flock','raise SystemExit(1)\n')
                exe('curl',f'''import pathlib,sys
args=sys.argv[1:];pathlib.Path(args[args.index('-o')+1]).write_bytes(b'corrupt' if {case=='corrupt'!r} else pathlib.Path({str(CURRENT)!r}).read_bytes())
if {case=='concurrent'!r}:pathlib.Path({str(target)!r}).write_bytes(b'concurrent code')
''')
                if case=='rollback':
                    marker=r/'fail-once';marker.touch()
                    exe('mv',f'''import os,pathlib,sys
marker=pathlib.Path({str(marker)!r});args=[a for a in sys.argv[1:] if a!='-f']
if marker.exists():marker.unlink();sys.exit(1)
os.replace(*args)
''')
                env=dict(os.environ,FX_FINALMASK_ROOT=str(r),PATH=str(r/'bin')+':'+os.environ['PATH'])
                result=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode==0,case=='success',result.stdout+result.stderr)
                self.assertEqual(target.read_bytes(),CURRENT.read_bytes() if case=='success' else b'concurrent code' if case=='concurrent' else before)
                backups=list((r/'root').iterdir());self.assertEqual(len(backups),1 if case in ('success','rollback') else 0)
                if case=='success':
                    self.assertEqual(backups[0].read_bytes(),before)
                    again=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=5)
                    self.assertEqual(again.returncode,0,again.stderr);self.assertEqual(len(list((r/'root').iterdir())),1)
                self.assertFalse(target.with_name('parser.uc.finalmask-new').exists())

if __name__=='__main__':unittest.main()
