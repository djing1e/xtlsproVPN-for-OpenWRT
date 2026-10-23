import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from test_dns_forward import MOCK
ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'

@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class DNSBind(unittest.TestCase):
    def test_preserves_upstreams_domains_dhcp_and_existing_exclusions(self):
        for existing in (None,'vpn0',['vpn0','wt0']):
            with self.subTest(existing=existing),tempfile.TemporaryDirectory() as tmp:
                d=Path(tmp);(d/'uci.uc').write_text(MOCK)
                data={'main':{'.type':'dnsmasq','server':['1.1.1.1','/corp/10.0.0.1'],'noresolv':'1','cachesize':'0'},
                      'second':{'.type':'dnsmasq','nonwildcard':'0'},'lan':{'.type':'dhcp','interface':'lan','ignore':'0'}}
                if existing is not None:data['main']['notinterface']=existing
                config=d/'dhcp.json';config.write_text(json.dumps(data))
                env=dict(os.environ,FX_DNS_DHCP_DIR=tmp)
                cmd=['ucode','-L',tmp,str(FILES/'usr/share/xray/lab/dns_bind.uc')]
                r=subprocess.run(cmd,env=env,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'changed')
                got=json.loads(config.read_text())
                for n in ('main','second'):
                    self.assertEqual(got[n]['nonwildcard'],'1');self.assertIn('wt0',got[n]['notinterface'])
                self.assertEqual(got['main']['notinterface'],['wt0'] if existing is None else ['vpn0','wt0'])
                for k in ('server','noresolv','cachesize'):self.assertEqual(got['main'][k],data['main'][k])
                self.assertEqual(got['lan'],data['lan'])
                before=config.read_bytes()
                r=subprocess.run(cmd,env=env,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'unchanged')
                self.assertEqual(config.read_bytes(),before)
                # A failed commit must be reported, never trigger a successful restart.
                got['main']['nonwildcard']='0';config.write_text(json.dumps(got));before=config.read_bytes()
                r=subprocess.run(cmd,env=dict(env,FAIL_COMMIT='1'),capture_output=True,text=True)
                self.assertNotEqual(r.returncode,0);self.assertEqual(config.read_bytes(),before)

    def test_wrapper_restarts_only_after_change_and_propagates_errors(self):
        for answer,code,restarted in [('changed',0,True),('unchanged',0,False),('changed',1,False)]:
            with self.subTest(answer=answer,code=code),tempfile.TemporaryDirectory() as tmp:
                d=Path(tmp);b=d/'netbird';b.write_text('');b.chmod(0o755)
                u=d/'ucode';u.write_text('#!/bin/sh\necho '+answer+'\nexit '+str(code)+'\n');u.chmod(0o755)
                restart=d/'dnsmasq';restart.write_text('#!/bin/sh\necho restart >> "'+str(d/'calls')+'"\n');restart.chmod(0o755)
                s=(FILES/'usr/bin/xray-dns-bind').read_text().replace('/usr/bin/netbird',str(b)).replace('result=$(ucode ','result=$('+str(u)+' ').replace('/etc/init.d/dnsmasq',str(restart))
                p=d/'run';p.write_text(s)
                r=subprocess.run(['sh',str(p)],capture_output=True,text=True)
                self.assertEqual(r.returncode==0,code==0);self.assertEqual((d/'calls').exists(),restarted)

if __name__=='__main__':unittest.main()
