"""Exercise the real installed-core updater and LAB post-switch injection in isolation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
MOCK=r'''#!/usr/bin/env python3
import json,os,sys,subprocess
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);name=Path(sys.argv[0]).name;a=sys.argv[1:];scenario=os.environ['SCENARIO'];binary=r/'lib/xray'
def version():return subprocess.check_output([str(binary),'version'],text=True).split()[1]
if name=='uname':print('aarch64')
elif name=='uci':
 key=a[-1]
 print({ 'xray_core.general.xray_bin':str(binary),'xray_lab_core.main.include_prerelease':'1','xray_lab_core.main.keep_previous':'0','xray_core.general.transparent_proxy_enable':'1' }.get(key,''))
elif name=='service':
 if a[0]=='running':sys.exit(0)
 assert a[0]=='restart'
 v=version()
 with (r/'events').open('a') as f:f.write('restart '+v+'\n')
 if (scenario=='restart-fail' and v=='26.10.10') or (scenario=='rollback-restart-fail' and v=='26.7.28'):sys.exit(1)
elif name=='real-ucode':
 if a[0].endswith('core_update.uc'):
  op=a[1]
  if op=='release-catalog':print('26.10.10')
  elif op=='ports':print(11500)
  elif op=='record':(r/'run/core-update.json').write_text(json.dumps({'phase':a[3]}))
  else:raise RuntimeError(a)
 elif a[0].endswith('control.uc'):
  if a[1]=='health':print('{"proxy_ok":true}')
  elif a[1]=='status':print('{"interception":{"active":true}}')
  else:raise RuntimeError(a)
 else:raise RuntimeError(a)
elif name=='curl':
 out=a[a.index('--output')+1]
 if out=='/dev/null':
  if scenario=='preflight-fail':sys.exit(28)
  print('204')
 else:Path(out).write_text('{}')
elif name=='df':print('Filesystem blocks used available cap mount\nfs 999999 0 999999 0 /overlay')
elif name=='jsonfilter':
 d=json.loads(Path(a[a.index('-i')+1]).read_text())
 for k in a[a.index('-e')+1].removeprefix('@.').split('.'):d=d[k]
 print(str(d).lower())
elif name=='nslookup':print('Name: openwrt.org\nAddress: 64.226.122.113')
elif name in ('sleep','sync'):pass
else:raise RuntimeError(name)
'''

class CoreAutoRollback(unittest.TestCase):
    def test_post_switch_failures_and_success(self):
        for scenario in ('injected-health','restart-fail','rollback-restart-fail','preflight-fail','success'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                r=Path(temp);tools=r/'tools';tools.mkdir();binary=r/'lib/xray';binary.parent.mkdir()
                def core(version):return '#!/bin/sh\nif [ "$1" = version ]; then echo "Xray '+version+' test"; else exit 0; fi\n'
                old=core('26.7.28');binary.write_text(old);binary.chmod(0o755)
                cache=r/'run/core-candidate';cache.mkdir(parents=True)
                new=core('26.10.10');(cache/'xray').write_text(new)
                (cache/'version').write_text('26.10.10');(cache/'expires').write_text(str(int(time.time())+1800))
                (cache/'sha256').write_text(hashlib.sha256(new.encode()).hexdigest())
                for name in ('uname','uci','service','real-ucode','curl','df','jsonfilter','nslookup','sleep','sync'):
                    p=tools/name;p.write_text(MOCK);p.chmod(0o755)
                # Use exactly the health rejection wrapper shipped in the LAB test script.
                script=(ROOT/'scripts/test-core-auto-rollback-lab.sh').read_text()
                wrapper=script.split('cat > "$WORK/bin/ucode" <<\'WRAP\'\n',1)[1].split('\nWRAP',1)[0]
                wrapper=wrapper.replace('/usr/libexec/forkop-xray/xray',str(binary)).replace('/usr/bin/ucode',str(tools/'real-ucode'))
                if scenario in ('success','preflight-fail','restart-fail'):
                    wrapper='#!/bin/sh\nexec '+str(tools/'real-ucode')+' "$@"\n'
                p=tools/'ucode';p.write_text(wrapper);p.chmod(0o755)
                source=(FILES/'usr/bin/xray-lab-core').read_text().replace('BIN=/usr/libexec/forkop-xray/xray','BIN='+str(binary)).replace('RUN=/var/run/xray-lab-control','RUN='+str(r/'run')).replace('/etc/init.d/xray_core',str(tools/'service'))
                command=r/'updater';command.write_text(source)
                env={**os.environ,'TEST_ROOT':str(r),'SCENARIO':scenario,'FX_TEST_ROOT':str(r),'FX_CORE_TEST_VERSION':'26.10.10','PATH':str(tools)+':'+os.environ['PATH']}
                result=subprocess.run(['sh',str(command),'install','26.10.10'],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode==0,scenario=='success',result.stdout+result.stderr)
                phase=json.loads((r/'run/core-update.json').read_text())['phase']
                if scenario=='success':
                    self.assertEqual(binary.read_text(),new);self.assertEqual(phase,'done')
                    self.assertFalse(Path(str(binary)+'.previous').exists())
                else:
                    self.assertEqual(binary.read_text(),old)
                    self.assertEqual(phase,'error' if scenario=='preflight-fail' else 'recovery_failed' if scenario=='rollback-restart-fail' else 'rolled_back')
                    if scenario!='preflight-fail':
                        self.assertEqual(Path(str(binary)+'.previous').read_text(),old)
                        self.assertEqual((r/'events').read_text(),'restart 26.10.10\nrestart 26.7.28\n')
                if scenario in ('injected-health','rollback-restart-fail'):
                    self.assertEqual((r/'injections').read_text().count('rejected-candidate'),3)
                else:self.assertFalse((r/'injections').exists())
                self.assertFalse(Path(str(binary)+'.next').exists())

if __name__=='__main__':unittest.main()
