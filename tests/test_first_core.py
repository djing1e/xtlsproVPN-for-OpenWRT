import unittest,tempfile,subprocess,os,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
class FirstCore(unittest.TestCase):
 def test_cold_catalog_test_install_and_invalid_candidate(self):
  for invalid in (False,True):
   with self.subTest(invalid=invalid),tempfile.TemporaryDirectory() as t:
    d=Path(t);tools=d/'tools';tools.mkdir();run=d/'run';bin=d/'lib/xray'
    candidate='#!/bin/sh\nif [ "$1" = version ]; then echo "Xray '+('26.7.11' if invalid else '26.7.28')+' test"; else exit 0; fi\n'
    digest=hashlib.sha256(b'zip').hexdigest()
    def tool(name,content):
     p=tools/name;p.write_text('#!/bin/sh\n'+content);p.chmod(0o755)
    tool('uname','echo aarch64\n')
    tool('uci','case "$*" in *xray_bin*) echo "'+str(bin)+'";; esac\n')
    tool('curl','printf "%s\\n" "$*" >> "'+str(d/'curl.log')+'"\nwhile [ "$#" -gt 0 ]; do if [ "$1" = --output ]; then shift; out=$1; fi; shift; done\nprintf zip > "$out"\n')
    tool('unzip',"if [ \"$1\" = -l ]; then echo '"+str(len(candidate.encode()))+" xray'; else cat '"+str(d/'candidate')+"'; fi\n")
    (d/'candidate').write_text(candidate)
    tool('df','printf "Filesystem 1024-blocks Used Available Capacity Mounted\\nfs 1000000 0 1000000 0%% /overlay\\n"\n')
    tool('service','echo service-called >> "'+str(d/'service-called')+'"; exit 1\n')
    tool('ucode','op=$2\ncase "$op" in release-catalog) echo 26.7.28;; checksum) echo '+digest+';; record) printf "%s\\n" "$*" >> "'+str(d/'records')+'";; ports) :;; esac\n')
    script=(ROOT/'usr/bin/xray-lab-core').read_text().replace('BIN=/usr/libexec/forkop-xray/xray','BIN='+str(bin)).replace('RUN=/var/run/xray-lab-control','RUN='+str(run)).replace('/etc/init.d/xray_core',str(tools/'service'))
    p=d/'command';p.write_text(script)
    env={**os.environ,'PATH':str(tools)+':'+os.environ['PATH']}
    def call(action):return subprocess.run(['sh',str(p),action,*(['26.7.28'] if action in ('test','install') else [])],env=env,text=True,capture_output=True)
    r=call('list');self.assertEqual(r.returncode,0,r.stderr);self.assertFalse(bin.exists())
    r=call('test')
    if invalid:
     self.assertNotEqual(r.returncode,0);self.assertFalse(bin.exists());continue
    self.assertEqual(r.returncode,0,r.stderr);self.assertFalse(bin.exists());self.assertIn('минимальную',r.stdout)
    r=call('install');self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertTrue(bin.exists());self.assertEqual((d/'curl.log').read_text().count('core.zip '),1);self.assertFalse((d/'service-called').exists());self.assertFalse(Path(str(bin)+'.previous').exists())
    r=call('test');self.assertNotEqual(r.returncode,0);self.assertTrue((d/'service-called').exists())
if __name__=='__main__':unittest.main()
