import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from test_netbird import UCI

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
LIB=FILES/'usr/share/xray/lab'

@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class Policy(unittest.TestCase):
    def decide(self, s, sample, now):
        code=f"import {{guard_decide}} from '{LIB}/netbird_guard_policy.mjs';printf('%J',guard_decide({json.dumps(s)},{json.dumps(sample)},{now}));"
        r=subprocess.run(['ucode','-e',code],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        return json.loads(r.stdout)

    def test_missing_and_hung_are_confirmed_before_recovery(self):
        for kind, delay, action in [('missing',60,'start'),('unresponsive',180,'restart')]:
            s={'started':0}; sample={'enabled':True,'uplink':True,kind:True}
            for t in [100,130]:
                s=self.decide(s,sample,t);self.assertIsNone(s['action'])
            s=self.decide(s,sample,100+delay)
            self.assertEqual(s['action'],action);self.assertEqual(s['attempts'],[100+delay])

    def test_offline_manual_auth_and_server_outage_never_restart(self):
        for reason,patch in [('waiting_uplink',{'uplink':False}),
            ('manual_down',{'manual_down':True}),('authentication_required',{'auth_required':True}),
            ('management_unavailable',{'management_reachable':False}),('paused',{'enabled':False})]:
            s={'started':0,'failure_since':0,'failures':8}
            s=self.decide(s,{'enabled':True,'uplink':True,**patch},1000)
            self.assertEqual(s['reason'],reason);self.assertIsNone(s['action']);self.assertEqual(s['failures'],0)

    def test_reconnection_recovers_without_restart(self):
        s=self.decide({'started':0},{'enabled':True,'uplink':True,'management_reachable':True},100)
        s=self.decide(s,{'enabled':True,'healthy':True},130)
        self.assertEqual(s['reason'],'healthy');self.assertFalse(s['attempts'])

    def test_hourly_budget_and_backoff_survive_healthy_samples(self):
        base={'started':0,'attempts':[900,930,960],'failure_since':900,'failures':8}
        s=self.decide(base,{'enabled':True,'uplink':True,'missing':True},1000)
        self.assertEqual(s['reason'],'rate_limited')
        s=self.decide(s,{'enabled':True,'healthy':True},1010)
        self.assertEqual(len(s['attempts']),3)
        s.update(failure_since=900,failures=8)
        s=self.decide(s,{'enabled':True,'uplink':True,'missing':True},5000)
        self.assertEqual(s['action'],'start');self.assertEqual(s['attempts'],[5000])
        s=self.decide({'started':0,'attempts':[800,990],'failure_since':900,'failures':8},
            {'enabled':True,'uplink':True,'missing':True},1000)
        self.assertEqual(s['reason'],'cooldown')

    def test_boot_grace_and_monotonic_reset(self):
        for s,t in [({},1000),({'started':2000,'attempts':[1900]},10)]:
            s=self.decide(s,{'enabled':True,'missing':True,'uplink':True},t)
            self.assertEqual(s['reason'],'startup_grace');self.assertFalse(s['attempts'])

MOCK='''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);n=Path(sys.argv[0]).name;a=sys.argv[1:]
with (r/'calls').open('a') as f:f.write(json.dumps([n,*a])+'\\n')
s=os.environ.get('SCENARIO','healthy')
if n=='service':sys.exit(1 if s=='service-fails' and a==['restart'] else 0)
if n=='pidof':print('123');sys.exit(1 if s=='missing' else 0)
if n=='ip':print('default via 192.0.2.1 dev eth1')
if n=='netbird':
 if s=='hung':sys.exit(124)
 print(json.dumps({'management':{'connected':s=='healthy'},'signal':{'connected':s=='healthy'},
  'netbirdIp':'100.64.0.1/16' if s=='healthy' else '',
  'daemonStatus':{'idle':'Idle','auth':'NeedsLogin'}.get(s,'Connecting')}))
if n=='curl':
 assert '--noproxy' in a and '--interface' in a and a[a.index('--interface')+1]=='eth1'
 assert '--insecure' not in a
 print('503' if s=='server-503' and 'nb.example.test' in a[-1] else '204',end='')
 sys.exit(1 if s=='offline' or s=='server-down' and 'nb.example.test' in a[-1] else 0)
'''

@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class GuardWorker(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.r=Path(self.tmp.name);self.run=self.r/'run';self.run.mkdir()
        b=self.r/'bin';b.mkdir();self.modules=self.r/'modules';self.modules.mkdir()
        (self.modules/'uci.uc').write_text(UCI)
        for name in ['service','netbird','pidof','ip','curl','logger']:
            p=b/name;p.write_text(MOCK);p.chmod(0o755)
        self.cfg=self.r/'uci.json';self.cfg.write_text(json.dumps({'xray_lab_netbird':{'main':{'enabled':'1','management_url':'https://nb.example.test'}}}))
        self.uptime=self.r/'uptime';self.uptime.write_text('1000.0 0')
        src=(LIB/'netbird_guard.uc').read_text().replace('/usr/share/xray/lab/netbird_guard_policy.mjs',str(LIB/'netbird_guard_policy.mjs'))
        src=src.replace('/var/run/xtlspro-netbird',str(self.run)).replace('/usr/bin/netbird',str(b/'netbird')).replace('/etc/init.d/netbird',str(b/'service')).replace('/proc/uptime',str(self.uptime))
        self.script=self.r/'guard.uc';self.script.write_text(src)
        self.env=dict(os.environ,PATH=str(b)+':'+os.environ['PATH'],TEST_ROOT=str(self.r),TEST_UCI_JSON=str(self.cfg))

    def tick(self,scenario,previous=None):
        if previous is not None:(self.run/'guard.json').write_text(json.dumps(previous))
        r=subprocess.run(['ucode','-L',str(self.modules),str(self.script)],env=dict(self.env,SCENARIO=scenario),capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        return json.loads((self.run/'guard.json').read_text())

    def calls(self):return [json.loads(x) for x in (self.r/'calls').read_text().splitlines()]

    def test_worker_classifies_and_recovers_without_mutating_config(self):
        original=self.cfg.read_bytes()
        for scenario,reason in [('healthy','healthy'),('idle','manual_down'),('auth','authentication_required'),
                                ('offline','waiting_uplink'),('server-down','management_unavailable'),
                                ('server-503','management_unavailable')]:
            self.assertEqual(self.tick(scenario,{'started':0})['reason'],reason)
        for scenario,action in [('missing','start'),('hung','restart'),('disconnected','restart'),('service-fails','restart')]:
            s=self.tick(scenario,{'started':0,'failure_since':100,'failures':3})
            self.assertEqual(s['action'],action)
            self.assertEqual(s['attempts'],[1000])
            self.assertEqual(s['command_ok'],scenario!='service-fails')
        self.assertEqual(self.cfg.read_bytes(),original)
        self.assertEqual((self.run/'guard.json').stat().st_mode&0o777,0o600)
        self.assertFalse(any(x[0]=='netbird' and x[1]!='status' for x in self.calls()))

    def test_settle_and_healthy_fast_path_avoid_network_probes(self):
        self.tick('disconnected',{'started':0,'settle_until':1100})
        self.tick('healthy',{'started':0})
        self.assertFalse(any(x[0]=='curl' for x in self.calls()))

    def test_management_reachability_is_enough_without_public_probes(self):
        s=self.tick('disconnected',{'started':0,'failure_since':100,'failures':3})
        self.assertEqual(s['action'],'restart')
        probes=[x[-1] for x in self.calls() if x[0]=='curl']
        self.assertEqual(probes,['https://nb.example.test'])

if __name__=='__main__':unittest.main()
