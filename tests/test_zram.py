import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from test_netbird import UCI
ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
MOCK=r'''#!/usr/bin/env python3
import os,json,sys
from pathlib import Path
r=Path(os.environ['FX_ZRAM_ROOT']);a=sys.argv[1:];name=Path(sys.argv[0]).name
with (r/'calls').open('a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='xray-zram-apk':
 if os.environ.get('SCENARIO')=='install-fails':sys.exit(1)
 import shutil
 shutil.copy2(r/'service-template',r/'etc/init.d/zram')
 sys.exit(0)
if a==['enabled']:sys.exit(0 if (r/'enabled').exists() else 1)
if a==['enable']:(r/'enabled').touch()
if a==['disable']:(r/'enabled').unlink(missing_ok=True)
if a==['stop']:
 if os.environ.get('SCENARIO')!='stop-fails':(r/'proc/swaps').write_text('Filename Type Size Used Priority\n')
if a==['start']:
 if os.environ.get('SCENARIO')=='start-fails':sys.exit(1)
 c=json.loads(Path(os.environ['TEST_UCI_JSON']).read_text())['system']['main']
 size=int(c.get('zram_size_mb',128))*1024-4
 if os.environ.get('SCENARIO')=='wrong-size':size=65532
 (r/'proc/swaps').write_text('Filename Type Size Used Priority\n/dev/zram0 partition '+str(size)+' 0 '+c.get('zram_priority','100')+'\n')
 algo=c.get('zram_comp_algo','lzo');(r/'sys/block/zram0/comp_algorithm').write_text(' '.join('['+x+']' if x==algo else x for x in ['lzo','lz4']))
'''
@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class Zram(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
  for n in ['proc','etc/init.d','sys/block/zram0','var/run/xtlspro-zram','usr/bin','modules']:(self.r/n).mkdir(parents=True)
  self.config=self.r/'uci.json';self.original={'system':{'main':{'.type':'system','hostname':'client','timezone':'MSK-3'}}};self.config.write_text(json.dumps(self.original))
  (self.r/'modules/uci.uc').write_text(UCI)
  (self.r/'proc/meminfo').write_text('MemTotal: 239568 kB\nMemAvailable: 64000 kB\n')
  (self.r/'proc/swaps').write_text('Filename Type Size Used Priority\n')
  (self.r/'sys/block/zram0/comp_algorithm').write_text('[lzo] lz4')
  for n in ['etc/init.d/zram','usr/bin/xray-zram-apk','service-template']:
   p=self.r/n;p.write_text(MOCK);p.chmod(0o755)
  self.env=dict(os.environ,FX_ZRAM_ROOT=str(self.r),TEST_UCI_JSON=str(self.config))
  self.params=dict(enabled='1',size_mb='128',algorithm='lzo')
 def call(self,mode,p=None,scenario='ok'):
  return subprocess.run(['ucode','-L',str(self.r/'modules'),str(FILES/'usr/share/xray/lab/zram.uc'),mode],input=json.dumps(p) if p is not None else '',capture_output=True,text=True,env=dict(self.env,SCENARIO=scenario),timeout=8)
 def calls(self):
  p=self.r/'calls';return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 def apply(self,p=None,scenario='ok'):
  x=self.call('stage',p or self.params);self.assertEqual(x.returncode,0,x.stderr+x.stdout)
  self.assertEqual((self.r/'var/run/xtlspro-zram/request.json').stat().st_mode&0o777,0o600)
  x=self.call('worker',scenario=scenario);self.assertEqual(x.returncode,0,x.stderr)
  return json.loads((self.r/'var/run/xtlspro-zram/job.json').read_text())
 def test_reading_status_never_installs_or_changes_configuration(self):
  (self.r/'etc/init.d/zram').unlink();x=self.call('status');self.assertEqual(x.returncode,0,x.stderr)
  s=json.loads(x.stdout);self.assertFalse(s['installed']);self.assertFalse(s['active']);self.assertEqual(s['size_mb'],128)
  self.assertEqual(self.calls(),[]);self.assertEqual(json.loads(self.config.read_text()),self.original)
 def test_enable_existing_and_idempotent_apply_preserve_system(self):
  self.assertEqual(self.apply()['state'],'done');s=json.loads(self.call('status').stdout)
  self.assertEqual(s['swaps'][0]['size_kb'],131068);self.assertTrue(s['enabled'])
  c=json.loads(self.config.read_text())['system']['main'];self.assertEqual(c['hostname'],'client');self.assertEqual(c['timezone'],'MSK-3')
  before=len([x for x in self.calls() if x[1:]==['start']]);self.assertEqual(self.apply()['state'],'done')
  self.assertEqual(len([x for x in self.calls() if x[1:]==['start']]),before)
 def test_install_is_explicit_and_verified(self):
  (self.r/'etc/init.d/zram').unlink();self.assertEqual(self.apply()['state'],'done')
  self.assertIn(['xray-zram-apk'],self.calls())
 def test_failed_install_keeps_configuration(self):
  (self.r/'etc/init.d/zram').unlink();self.assertEqual(self.apply(scenario='install-fails')['state'],'failed')
  self.assertEqual(json.loads(self.config.read_text()),self.original)
 def test_unsafe_disable_and_resize_rejected_before_changes(self):
  self.assertEqual(self.apply()['state'],'done')
  (self.r/'proc/swaps').write_text('Filename Type Size Used Priority\n/dev/zram0 partition 131068 60000 100\n')
  before=self.config.read_bytes();calls=len(self.calls())
  for p in [dict(self.params,enabled='0'),dict(self.params,size_mb='256')]:
   self.assertEqual(self.apply(p)['state'],'failed');self.assertEqual(self.config.read_bytes(),before)
  self.assertNotIn(['zram','stop'],self.calls()[calls:])
 def test_disable_frees_swap_and_persists_autostart_off(self):
  self.apply();self.assertEqual(self.apply(dict(self.params,enabled='0'))['state'],'done')
  self.assertFalse(json.loads(self.call('status').stdout)['active']);self.assertFalse((self.r/'enabled').exists())
 def test_invalid_input_is_rejected_at_stage(self):
  for p in [dict(self.params,size_mb='1024'),dict(self.params,size_mb='128;reboot'),dict(self.params,algorithm='evil'),dict(self.params,enabled=True)]:
   x=self.call('stage',p);self.assertNotEqual(x.returncode,0);self.assertEqual(json.loads(self.config.read_text()),self.original)
 def test_foreign_zram_is_not_touched(self):
  (self.r/'proc/swaps').write_text('Filename Type Size Used Priority\n/dev/zram1 partition 131068 0 100\n')
  self.assertNotEqual(self.call('stage',self.params).returncode,0);self.assertEqual(json.loads(self.config.read_text()),self.original)
 def test_switch_compression_requires_verified_restart(self):
  self.apply();self.assertEqual(self.apply(dict(self.params,algorithm='lz4'))['state'],'done')
  self.assertEqual(json.loads(self.call('status').stdout)['active_algorithm'],'lz4')
 def test_commit_failure_never_stops_active_swap(self):
  self.apply();before=self.config.read_bytes();calls=len(self.calls())
  p=self.r/'modules/uci.uc';p.write_text(UCI.replace("commit:function(p){return", "commit:function(p){if(getenv('FAIL_COMMIT'))return false;return"))
  self.env['FAIL_COMMIT']='1'
  self.assertEqual(self.apply(dict(self.params,size_mb='256'))['state'],'failed')
  self.assertEqual(self.config.read_bytes(),before);self.assertNotIn(['zram','stop'],self.calls()[calls:])
 def test_start_failure_restores_previous_fields(self):
  self.assertEqual(self.apply(scenario='start-fails')['state'],'failed');self.assertEqual(json.loads(self.config.read_text()),self.original)
 def test_stop_failure_does_not_start_second_swap(self):
  self.apply();before=len(self.calls());j=self.apply(dict(self.params,size_mb='256'),scenario='stop-fails')
  self.assertEqual(j['state'],'failed');self.assertNotIn(['zram','start'],self.calls()[before:])
  self.assertEqual(json.loads(self.config.read_text())['system']['main']['zram_size_mb'],'128')
 def test_wrong_runtime_settings_are_not_reported_as_success(self):
  self.assertEqual(self.apply(scenario='wrong-size')['state'],'failed');self.assertEqual(json.loads(self.config.read_text()),self.original)
if __name__=='__main__':unittest.main()
