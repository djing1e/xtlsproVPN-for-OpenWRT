import json,os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
MOCK='''#!/usr/bin/env python3
import os,sys,json,time,subprocess,signal
from pathlib import Path
root=Path(os.environ['TEST_ROOT']);scenario=os.environ['TEST_SCENARIO'];name=Path(sys.argv[0]).name;a=sys.argv[1:]
state=root/'service-state';core=root/'xray_core';events=root/'events'
def event(v):
 with events.open('a') as f:f.write(v+'\\n')
if name=='uci':print('1')
elif name=='init':
 if a[0]=='running':sys.exit(0)
 if a[0]=='restart':
  value='new' if core.read_text()=='new-core' else 'old';state.write_text(value);event('restart-'+value)
  if (scenario=='restart-fail' and value=='new') or (scenario=='rollback-restart-fail' and value=='old'):sys.exit(1)
elif name=='forkop-xray':
 target=Path(os.environ['FX_STATE_DIR']);(target/'subscription.json').write_text('new-catalogue');(target/'previous.json').write_text('old-catalogue')
 event('fetch')
 if scenario=='download-fail':sys.exit(1)
elif name=='ucode':
 if a[0]=='-':
  body=sys.stdin.read()
  if 'function norm' in body:sys.exit(0 if scenario=='unchanged' else 1)
 elif a[0].endswith('lab_prepare.uc'):
  Path(a[1]+'/xray_core').write_text('new-core');event('prepare')
 elif a[0].endswith('gen_config.uc'):print('{}')
 elif a[0].endswith('sync_probe.uc'):
  sequential=scenario.startswith('sequential')
  Path(a[3]).write_text('{}')
  if sequential:
   Path(a[3]+'.0').write_text('{}');Path(a[3]+'.1').write_text('{}')
   Path(a[4]).write_text('12000 '+a[3]+'.0 0\\n11980 '+a[3]+'.1 1\\n')
  else:Path(a[4]).write_text('12000\\n')
  Path(a[7]).write_text(json.dumps({'mode':'sequential' if sequential else 'independent','minimum_kb':32768 if sequential else 98304,'gomemlimit':'24MiB' if sequential else '64MiB'}))
 elif a[0].endswith('control.uc'):
  current=state.read_text();fail=(scenario in ('live-health-fail','rollback-copy-fail','rollback-restart-fail','rollback-health-fail') and current=='new') or (scenario=='rollback-health-fail' and current=='old' and 'restart-old' in events.read_text())
  print(json.dumps({'proxy_ok':not fail} if a[1]=='health' else {'interception':{'active':True}}))
elif name=='xray':
 if '-test' in a:
  if scenario=='config-fail':sys.exit(1)
 else:
  event('probe-start')
  def stop(*args):
   event('probe-stop');sys.exit(0)
  signal.signal(signal.SIGTERM,stop);time.sleep(60)
elif name=='utpl':print('')
elif name=='nft':
 if scenario=='nft-fail':sys.exit(1)
elif name=='curl':
 if scenario in ('candidate-fail','sequential-candidate-fail'):sys.exit(1)
 print('204')
elif name=='nslookup':
 if (scenario in ('candidate-dns-fail','sequential-dns-fail') and a[-1].endswith(':11981')) or (scenario=='live-dns-fail' and state.read_text()=='new'):sys.exit(1)
 print('Name: openwrt.org\\nAddress: 64.226.122.113')
elif name=='jsonfilter':
 d=json.loads(Path(a[a.index('-i')+1]).read_text())
 for k in a[a.index('-e')+1].removeprefix('@.').split('.'):d=d[k]
 print(str(d).lower())
elif name=='mv':
 if a[-1].endswith('/committed') and scenario=='commit-before-fail':sys.exit(1)
 subprocess.run(['/bin/mv']+a,check=True)
 if a[-1].endswith('/committed') and scenario=='commit-after-fail':sys.exit(1)
elif name=='cp':
 if scenario=='rollback-copy-fail' and a[-1].endswith('xray_core.rollback'):sys.exit(1)
 os.execv('/bin/cp',['cp']+a)
elif name in ('sleep','sync'):pass
else:raise RuntimeError(name)
'''
class SyncTransaction(unittest.TestCase):
 def test_failures_preserve_or_restore_working_state(self):
  for scenario in ('download-fail','config-fail','nft-fail','candidate-fail','candidate-dns-fail','restart-fail','live-health-fail','live-dns-fail','success','unchanged','rollback-copy-fail','rollback-restart-fail','rollback-health-fail','commit-before-fail','commit-after-fail','sequential-success','sequential-candidate-fail','sequential-dns-fail','low-memory'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as t:
    p=Path(t);tools=p/'tools';tools.mkdir();state=p/'catalogue';state.mkdir();run=p/'run';run.mkdir()
    (state/'subscription.json').write_text('old-catalogue');(state/'device-hwid-short').write_text('original-id');(p/'xray_core').write_text('old-core');(p/'service-state').write_text('old');(p/'events').write_text('');(p/'meminfo').write_text('MemAvailable: '+('10000' if scenario=='low-memory' else '49152' if scenario.startswith('sequential') else '200000')+' kB\n')
    for name in ('uci','init','forkop-xray','ucode','xray','utpl','nft','curl','nslookup','jsonfilter','sleep','cp','sync','mv'):
     f=tools/name;f.write_text(MOCK);f.chmod(0o755)
    source=(ROOT/'usr/bin/xray-lab-sync-safe').read_text().replace('RUN=/var/run/xray-lab-control','RUN='+str(run)).replace('STATE=/etc/forkop-xray','STATE='+str(state)).replace('CORE=/etc/config/xray_core','CORE='+str(p/'xray_core')).replace('INIT=/etc/init.d/xray_core','INIT='+str(tools/'init')).replace('BIN=/usr/libexec/forkop-xray/xray','BIN='+str(tools/'xray')).replace('/etc/xtlsprovpn-last-apply-failure.log',str(p/'failure.log')).replace('/tmp/xtls-sync-safe.',str(p/'work.'))
    journal=(ROOT/'usr/bin/xray-lab-subscription-journal').read_text().replace('RUN=/var/run/xray-lab-control','RUN='+str(run)).replace('STATE=/etc/forkop-xray','STATE='+str(state)).replace('CORE=/etc/config/xray_core','CORE='+str(p/'xray_core'))
    helper=tools/'journal';helper.write_text(journal);helper.chmod(0o755)
    source=source.replace('JOURNAL=/usr/bin/xray-lab-subscription-journal','JOURNAL='+str(helper))
    source=source.replace('/proc/meminfo',str(p/'meminfo'))
    command=p/'sync';command.write_text(source)
    env={**os.environ,'PATH':str(tools)+':'+os.environ['PATH'],'TEST_ROOT':str(p),'TEST_SCENARIO':scenario}
    r=subprocess.run(['sh',str(command)],env=env,capture_output=True,text=True,timeout=20)
    success=scenario in ('success','unchanged','sequential-success');self.assertEqual(r.returncode==0,success,r.stdout+r.stderr)
    self.assertEqual((state/'subscription.json').read_text(),'new-catalogue' if success or scenario.startswith('commit-') else 'old-catalogue')
    self.assertEqual((p/'xray_core').read_text(),'new-core' if scenario in ('success','sequential-success','rollback-copy-fail','commit-before-fail','commit-after-fail') else 'old-core')
    self.assertEqual((state/'device-hwid-short').read_text(),'original-id')
    marker=run/'subscription-recovery'
    if scenario.startswith('rollback-'):
     self.assertTrue(marker.is_file(),r.stdout+r.stderr)
     saved=Path(marker.read_text().strip());self.assertEqual((saved/'previous-core').read_text(),'old-core')
     self.assertIn('Recovery snapshot retained',r.stdout)
     before=(p/'events').read_text()
     again=subprocess.run(['sh',str(command)],env=env,capture_output=True,text=True,timeout=5)
     self.assertNotEqual(again.returncode,0);self.assertEqual((p/'events').read_text(),before)
    else:self.assertFalse(marker.exists())
    if scenario.startswith('commit-'):
     self.assertTrue((state/'.subscription-transaction').is_dir())
     recovered=subprocess.run([str(helper),'recover'],env=env,capture_output=True,text=True,timeout=5)
     self.assertEqual(recovered.returncode,0,recovered.stderr)
     self.assertEqual((p/'xray_core').read_text(),'old-core' if scenario=='commit-before-fail' else 'new-core')
     self.assertEqual((state/'subscription.json').read_text(),'old-catalogue' if scenario=='commit-before-fail' else 'new-catalogue')
    events=(p/'events').read_text()
    active=0
    for line in events.splitlines():
     if line=='probe-start':active+=1;self.assertLessEqual(active,1)
     if line=='probe-stop':active-=1
    if scenario=='sequential-success':self.assertEqual(events.count('probe-start'),2)
    if scenario.startswith(('download','config','nft','candidate')) or scenario in ('unchanged','low-memory','sequential-candidate-fail','sequential-dns-fail'):self.assertNotIn('restart-',events)
    if scenario in ('restart-fail','live-health-fail','live-dns-fail'):self.assertIn('restart-old',events);self.assertEqual((p/'service-state').read_text(),'old')
if __name__=='__main__':unittest.main()
