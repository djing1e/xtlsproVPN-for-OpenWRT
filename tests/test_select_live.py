import copy,json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];FILES=ROOT/'package/xtlsprovpn/files'
MOCK=r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);a=sys.argv[1:];name=Path(sys.argv[0]).name
with (r/'calls').open('a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='curl':
 print('000' if os.environ.get('SCENARIO')=='failed-https' else '204');sys.exit(0)
if a[:2]==['api','bi']:
 target=(r/'override').read_text();tag='fx_node:cfgbbbbbb' if a[-1]=='fx_auto_pool' else 'fx_node:cfgaaaaaa'
 print(json.dumps({'balancer':{'override':{'target':target},'principleTarget':{'tag':[tag]}}}))
elif a[:2]==['api','bo']:
 (r/'override').write_text('' if a[-1]=='-r' else a[-1])
 if os.environ.get('SCENARIO')=='api-timeout' and not (r/'timed-out').exists():
  (r/'timed-out').touch();sys.exit(1)
else:raise RuntimeError(a)
'''
@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class SelectLive(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
  self.bin=self.r/'bin';self.bin.mkdir()
  for name in ['xray','curl']:
   p=self.bin/name;p.write_text(MOCK);p.chmod(0o755)
  self.live={'outbounds':[{'tag':'fx_node:'+n,'protocol':'vless'} for n in ['cfgaaaaaa','cfgbbbbbb']]+[{'tag':'fx_auto','protocol':'loopback','settings':{'inboundTag':'fx_auto_dispatch'}}],
   'inbounds':[{'tag':'fx_probe:'+n,'protocol':'socks','listen':'127.0.0.1','port':11500+i} for i,n in enumerate(['cfgaaaaaa','cfgbbbbbb'])],
   'routing':{'balancers':[{'tag':'fx_main','selector':['fx_node:cfgaaaaaa'],'strategy':{'type':'random'},'fallbackTag':'blackhole_outbound'},{'tag':'fx_auto_pool','selector':['fx_node:cfgaaaaaa','fx_node:cfgbbbbbb'],'strategy':{'type':'leastPing'}}]}}
  self.runtime=self.r/'live.json';self.runtime.write_text(json.dumps(self.live));self.core=self.r/'core';self.core.write_text('old-selection')
  self.stage=self.r/'stage';self.stage.mkdir();(self.stage/'xray_core').write_text('new-selection')
  self.candidate=copy.deepcopy(self.live);self.candidate['routing']['balancers'][0]['selector']=['fx_node:cfgbbbbbb']
  (self.stage/'config.json').write_text(json.dumps(self.candidate));(self.r/'override').write_text('fx_node:cfgaaaaaa')
  source=(FILES/'usr/share/xray/lab/select_live.uc').read_text().replace('/usr/libexec/forkop-xray/xray',str(self.bin/'xray')).replace('/var/etc/xray/config.json',str(self.runtime)).replace('/etc/config/xray_core',str(self.core)).replace('/var/run/xray-lab-control/selection.json',str(self.r/'selection.json'))
  self.script=self.r/'select.uc';self.script.write_text(source)
 def call(self,location='cfgbbbbbb',scenario='ok'):
  return subprocess.run(['ucode',str(self.script),str(self.stage),location],env=dict(os.environ,TEST_ROOT=str(self.r),PATH=str(self.bin)+':'+os.environ['PATH'],SCENARIO=scenario),text=True,capture_output=True,timeout=10)
 def test_hot_manual_selection_persists_without_service_or_firewall_calls(self):
  p=self.call();self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(self.core.read_text(),'new-selection');self.assertEqual((self.r/'override').read_text(),'fx_node:cfgbbbbbb')
  self.assertNotIn('restart',(self.r/'calls').read_text());self.assertNotIn('firewall',(self.r/'calls').read_text())
 def test_auto_after_manual_boot_uses_full_auto_pool(self):
  p=self.call('auto');self.assertEqual(p.returncode,0,p.stderr);self.assertEqual((self.r/'override').read_text(),'fx_auto')
 def test_https_failure_and_uncertain_api_restore_old_selection(self):
  for scenario in ['failed-https','api-timeout']:
   with self.subTest(scenario=scenario):
    original=self.runtime.read_text();p=self.call(scenario=scenario);self.assertNotEqual(p.returncode,0);self.assertEqual(self.core.read_text(),'old-selection');self.assertEqual(self.runtime.read_text(),original);self.assertEqual((self.r/'override').read_text(),'fx_node:cfgaaaaaa')
 def test_changed_transport_is_rejected_before_override(self):
  self.candidate['outbounds'][0]['protocol']='socks';(self.stage/'config.json').write_text(json.dumps(self.candidate))
  p=self.call();self.assertNotEqual(p.returncode,0);self.assertFalse((self.r/'calls').exists());self.assertEqual(self.core.read_text(),'old-selection')
if __name__=='__main__':unittest.main()
