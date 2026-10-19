import shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
class ExecutableModes(unittest.TestCase):
 def test_checker_rejects_lost_execute_bit_in_each_entrypoint_family(self):
  with tempfile.TemporaryDirectory() as tmp:
   copy=Path(tmp)/'files';shutil.copytree(FILES,copy)
   for name in ['etc/init.d/xray_core','etc/uci-defaults/'+next((copy/'etc/uci-defaults').iterdir()).name,'usr/bin/xray-lab-control','usr/libexec/rpcd/xray_lab_netbird']:
    with self.subTest(path=name):
     p=copy/name;old=p.stat().st_mode;p.chmod(0o644)
     r=subprocess.run([sys.executable,str(ROOT/'scripts/check-source.py'),str(copy)],capture_output=True,text=True)
     self.assertNotEqual(r.returncode,0);self.assertIn('Missing executable permissions: '+name,r.stderr)
     p.chmod(old)
   r=subprocess.run([sys.executable,str(ROOT/'scripts/check-source.py'),str(copy)],capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stderr)
if __name__=='__main__':unittest.main()
