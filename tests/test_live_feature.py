import json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
import test_native_catalogue as native
ROOT=Path(__file__).resolve().parents[1];FILES=ROOT/'package/xtlsprovpn/files'
@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class LiveFeature(unittest.TestCase):
 def test_auto_loopback_survives_profile_and_manual_boot(self):
  for mode in ['manual','auto']:
   for profile in ['', 'roscomvpn']:
    with self.subTest(mode=mode,profile=profile),tempfile.TemporaryDirectory() as t:
     d=Path(t);base={'outbounds':[{'tag':'blackhole_outbound','protocol':'blackhole'}],'inbounds':[],'routing':{'rules':[],'balancers':[]},'dns':{'servers':[{}]},'policy':{}}
     config={'general':{'fx_dashboard':'1','fx_mode':mode,'fx_location':'cfgaaaaaa','fx_routing':profile}}
     for name in ['cfgaaaaaa','cfgbbbbbb']:config[name]={'.type':'servers','protocol':'vless','server':name+'.test','server_port':'443','password':'00000000-0000-4000-8000-000000000001','transport':'tcp','vless_tls':'none'}
     (d/'profile.json').write_text(json.dumps(dict(GlobalProxy='true',RouteOrder='block-proxy-direct',DomainStrategy='IPIfNonMatch',FakeDNS='false',DirectSites=[],DirectIp=[],ProxySites=[],ProxyIp=[],BlockSites=[],BlockIp=[],Geoipurl='https://cdn.jsdelivr.net/gh/hydraponique/roscomvpn-geoip@202610160805/release/geoip.dat',Geositeurl='https://cdn.jsdelivr.net/gh/hydraponique/roscomvpn-geosite@202610120948/release/geosite.dat',RemoteDNSDomain='https://8.8.8.8/dns-query',DomesticDNSDomain='https://77.88.8.8/dns-query',DnsHosts={})))
     (d/'in.json').write_text(json.dumps([base,config]));(d/'run.uc').write_text("import { lab_features } from '"+str(FILES/'usr/share/xray/feature/lab.mjs')+"';let a=json(require('fs').readfile(ARGV[0]));printf('%J',lab_features(a[0],a[1]));")
     r=subprocess.run(['ucode',str(d/'run.uc'),str(d/'in.json')],env=dict(os.environ,FX_ROSCOM_PROFILE=str(d/'profile.json')),capture_output=True,text=True)
     self.assertEqual(r.returncode,0,r.stderr);c=json.loads(r.stdout)
     auto=next(b for b in c['routing']['balancers'] if b['tag']=='fx_auto_pool');self.assertEqual(auto['selector'],['fx_node:cfgaaaaaa','fx_node:cfgbbbbbb'])
     self.assertTrue(any(x.get('inboundTag')==['fx_auto_dispatch'] and x.get('balancerTag')=='fx_auto_pool' for x in c['routing']['rules']))
     main=next(b for b in c['routing']['balancers'] if b['tag']=='fx_main');self.assertEqual(len(main['selector']),1 if mode=='manual' else 2)
 def test_native_generator_selection_changes_only_main_balancer(self):
  self.enc='none';self.pub='A'*43;native.CatalogueTests.setUp(self)
  u=native.CatalogueTests.prepare(self);u['general'].update(fx_dashboard='1',fx_mode='manual')
  names=sorted(k for k,v in u.items() if v.get('.type')=='servers');u['general']['fx_location']=names[0]
  outputs=[]
  for mode,selected in [('manual',names[0]),('manual',names[1]),('auto',names[1])]:
   u['general'].update(fx_mode=mode,fx_location=selected,tcp_balancer_v4=names if mode=='auto' else [selected],udp_balancer_v4=names if mode=='auto' else [selected])
   (self.d/'stage/xray_core').write_text(json.dumps(u))
   r=subprocess.run(['ucode','-L',str(self.d/'modules'),str(FILES/'usr/share/xray/gen_config.uc')],env=self.env,capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stderr);c=json.loads(r.stdout)
   b=next(b for b in c['routing']['balancers'] if b['tag']=='fx_main');del b['selector'];del b['strategy'];outputs.append(c)
  self.assertEqual(outputs[0],outputs[1]);self.assertEqual(outputs[1],outputs[2])
if __name__=='__main__':unittest.main()
