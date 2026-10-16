import hashlib,os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
class BootstrapSafety(unittest.TestCase):
 def test_failure_does_not_publish_core_or_change_network(self):
  for scenario in ('download','checksum','version','config','copy','success'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as t:
    d=Path(t);tools=d/'tools';tools.mkdir();run=d/'run';binary=d/'lib/xray';binary.parent.mkdir()
    def tool(name,body):
     p=tools/name;p.write_text('#!/bin/sh\n'+body);p.chmod(0o755)
    candidate='#!/bin/sh\nif [ "$1" = version ]; then echo "Xray '+('0.0.0' if scenario=='version' else '26.7.28')+'"; else exit '+('1' if scenario=='config' else '0')+'; fi\n'
    (d/'candidate').write_text(candidate)
    tool('uname','echo aarch64\n')
    tool('curl','echo "$*" >> "'+str(d/'requests')+'"\n'+('exit 28\n' if scenario=='download' else 'while [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then shift; out=$1; fi; shift; done\nprintf zip > "$out"\n'))
    tool('ucode','echo '+('bad' if scenario=='checksum' else hashlib.sha256(b'zip').hexdigest())+'\n')
    tool('unzip','if [ "$1" = -l ]; then echo "'+str(len(candidate.encode()))+' xray"; else cat "'+str(d/'candidate')+'"; fi\n')
    tool('df','printf "Filesystem blocks used available cap mount\\nfs 999999 0 999999 0 /overlay\\n"\n')
    if scenario=='copy':tool('cp','touch "$2"; exit 1\n')
    for name in ('uci','ip','nft','ubus','service'):
     tool(name,'echo called >> "'+str(d/'network-mutated')+'"; exit 1\n')
    source=(ROOT/'usr/bin/xtlspro-core-bootstrap').read_text().replace('/usr/libexec/forkop-xray/xray',str(binary)).replace('/var/run/xray-lab-control',str(run)).replace('/proc/meminfo',str(d/'meminfo'))
    (d/'meminfo').write_text('MemAvailable: 200000 kB\n');script=d/'bootstrap';script.write_text(source)
    r=subprocess.run(['sh',str(script),'26.7.28'],env={**os.environ,'PATH':str(tools)+':'+os.environ['PATH']},capture_output=True,text=True,timeout=10)
    self.assertEqual(r.returncode==0,scenario=='success',r.stdout+r.stderr)
    self.assertEqual(binary.exists(),scenario=='success')
    self.assertFalse(Path(str(binary)+'.new').exists())
    self.assertFalse((d/'network-mutated').exists())
    request=(d/'requests').read_text();self.assertIn('--max-time 900',request);self.assertIn('--speed-time 30',request)
if __name__=='__main__':unittest.main()
