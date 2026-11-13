import os,re,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class UpgradeMonitor(unittest.TestCase):
    def test_postinstall_restarts_only_an_already_running_monitor(self):
        for running in (True,False):
            with self.subTest(running=running),tempfile.TemporaryDirectory() as temp:
                r=Path(temp);(r/'bin').mkdir();(r/'etc/init.d').mkdir(parents=True);(r/'tmp').mkdir()
                uci=r/'bin/uci';uci.write_text('#!/bin/sh\nexit 0\n');uci.chmod(0o755)
                for name in ('xray_lab_recovery','xray_lab_monitor','rpcd','xray_core','netbird','xray_netbird_guard','xray_rescue_watch'):
                    p=r/'etc/init.d'/name
                    p.write_text(f'''#!/bin/sh
echo '{name}' "$1" >> '{r}/calls'
if [ "$1" = running ];then exit {0 if running else 1};fi
exit 0
''');p.chmod(0o755)
                source=(ROOT/'package/xtlsprovpn/files/etc/uci-defaults/99-xtlsprovpn').read_text()
                source=re.sub(r'/(etc|var|tmp)/',lambda m:str(r)+m[0],source)
                script=r/'postinst.sh';script.write_text(source)
                result=subprocess.run(['sh',str(script)],env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH']),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                calls=(r/'calls').read_text().splitlines()
                self.assertEqual([x for x in calls if x.startswith('xray_lab_monitor ')],['xray_lab_monitor running']+(['xray_lab_monitor restart'] if running else []))
                self.assertFalse(any(x.startswith(('xray_core ','netbird ')) for x in calls))

if __name__=='__main__':unittest.main()
