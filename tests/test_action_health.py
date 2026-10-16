import os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
class Health(unittest.TestCase):
 def test_false_json_is_a_failed_action(self):
  source=(ROOT/'usr/bin/xray-lab-control').read_text();fn=source[source.index('    require_health()'):source.index('    case "$op" in\n    start)')]
  for value in ('true','false'):
   with self.subTest(value=value),tempfile.TemporaryDirectory() as t:
    p=Path(t)
    for name,body in {'ucode':'echo \'{"proxy_ok":'+value+'}\'','jsonfilter':'echo '+value}.items():
     f=p/name;f.write_text('#!/bin/sh\n'+body+'\n');f.chmod(0o755)
    r=subprocess.run(['sh','-c','set -eu\nUC=unused\nRUN='+str(p)+'\n'+fn+'\nrequire_health'],env={**os.environ,'PATH':str(p)+':'+os.environ['PATH']},capture_output=True,text=True)
    self.assertEqual(r.returncode==0,value=='true',r.stderr)
if __name__=='__main__':unittest.main()
