import json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
from test_netbird import UCI
ROOT=Path(__file__).resolve().parents[1];FILES=ROOT/'package/xtlsprovpn/files';LIB=FILES/'usr/share/xray/lab'
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI'+'A'*43

@unittest.skipUnless(shutil.which('ucode'),'ucode required')
class Policy(unittest.TestCase):
    def decide(self,s,sample,t):
        code=f"import {{rescue_decide}} from '{LIB}/rescue_policy.mjs';printf('%J',rescue_decide({json.dumps(s)},{json.dumps(sample)},{t}));"
        r=subprocess.run(['ucode','-e',code],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_auto_waits_five_minutes_then_keeps_recovery_grace(self):
        sample={'enabled':True,'netbird_enabled':True};s={}
        for t in [100,200,399]:
            s=self.decide(s,sample,t);self.assertIsNone(s['action'])
        s=self.decide(s,sample,400);self.assertEqual(s['action'],'start')
        sample.update(running=True,established=True,healthy=True)
        for t in [430,900]:s=self.decide(s,sample,t);self.assertIsNone(s['action'])
        s=self.decide(s,sample,1030);self.assertEqual(s['action'],'stop')
    def test_manual_open_close_and_disable(self):
        sample={'enabled':True,'healthy':True}
        s=self.decide({'manual_until':1000},sample,100);self.assertEqual(s['action'],'start')
        sample['running']=True;s=self.decide({'pause_until':1000},sample,100);self.assertEqual(s['action'],'stop')
        s=self.decide({},dict(sample,enabled=False),100);self.assertEqual(s['reason'],'disabled');self.assertEqual(s['action'],'stop')
        for flag in [{'manual_down':True},{'netbird_enabled':False}]:
            s=self.decide({'outage_since':1},dict(enabled=True,netbird_enabled=True,**flag) if 'netbird_enabled' not in flag else dict(enabled=True,**flag),1000)
            self.assertIsNone(s['action'])
    def test_dead_service_backoff_and_hung_tcp_timeout(self):
        sample={'enabled':True,'netbird_enabled':True};s={'outage_since':0}
        for t,delay in [(400,30),(430,60),(490,120),(610,300),(910,300)]:
            s=self.decide(s,sample,t);self.assertEqual(s['action'],'start');self.assertEqual(s['retry_at'],t+delay)
            s=self.decide(s,sample,t+1);self.assertIsNone(s['action'])
        s=self.decide(s,dict(sample,running=True),1000);self.assertEqual(s['reason'],'connect_timeout');self.assertEqual(s['action'],'stop')

MOCK='''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);n=Path(sys.argv[0]).name;a=sys.argv[1:];scenario=os.environ.get('SCENARIO','healthy')
with (r/'calls').open('a') as f:f.write(json.dumps([n,*a])+'\\n')
if n=='ip':
 if '-j' in a:print(json.dumps([{'dev':'wt0' if scenario=='wrong-route' else 'wan','prefsrc':'192.0.2.2'}]))
 else:print('default via 192.0.2.1 dev wan')
elif n=='netbird':print(json.dumps({'management':{'connected':scenario=='healthy'},'signal':{'connected':True},'netbirdIp':'100.64.0.1/16','daemonStatus':'Connecting'}))
elif n=='netbird-service':sys.exit(1 if scenario=='nb-disabled' else 0)
elif n=='dropbearkey':
 if '-t' in a:Path(a[a.index('-f')+1]).write_text('private-key-must-never-escape');Path(a[a.index('-f')+1]).chmod(0o600)
 else:print('Public key portion is:\\n'+os.environ['PUBKEY'])
elif n=='tunnel':
 if a==['start']:
  if scenario=='reject':sys.exit(1)
  (r/'running').touch()
 elif a==['stop']:(r/'running').unlink(missing_ok=True)
elif n=='ubus':
 print(json.dumps({'xray_rescue_tunnel':{'instances':{'instance1':{'running':True,'pid':123}}}}) if (r/'running').exists() else '{}')
'''

@unittest.skipUnless(shutil.which('ucode'),'ucode required')
class Controller(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
        self.run=self.r/'run';self.run.mkdir();self.identity=self.r/'identity';self.identity.mkdir()
        self.key=self.identity/'id_ed25519';self.key.write_text('private-key-must-never-escape');self.key.chmod(0o600)
        self.known=self.r/'known_hosts';self.proc=self.r/'proc';(self.proc/'123/fd').mkdir(parents=True)
        (self.proc/'123/cmdline').write_text('dbclient\\0'+str(self.key));(self.proc/'123/status').write_text('VmRSS: 2500 kB')
        (self.proc/'net').mkdir();(self.proc/'net/tcp').write_text('0: 0:0 0:0 01 0 0 0 0 0 4242')
        (self.proc/'123/fd/3').symlink_to('socket:[4242]')
        self.uptime=self.r/'uptime';self.uptime.write_text('1000.0 0')
        b=self.r/'bin';b.mkdir();mods=self.r/'modules';mods.mkdir();self.mods=mods;(mods/'uci.uc').write_text(UCI)
        for name in ['ip','netbird','netbird-service','dropbearkey','dbclient','tunnel','watch','ubus','logger']:
            p=b/name;p.write_text(MOCK);p.chmod(0o755)
        self.cfg=self.r/'uci.json';self.cfg.write_text(json.dumps({'xray_lab_rescue':{'main':{'enabled':'0'}},'xray_lab_dns':{'main':{'output_enabled':'0'}}}))
        src=(LIB/'rescue.uc').read_text().replace('/usr/share/xray/lab/rescue_policy.mjs',str(LIB/'rescue_policy.mjs'))
        for old,new in [('/var/run/xtlspro-rescue',str(self.run)),('/etc/xtlspro-rescue',str(self.identity)),('/root/.ssh/known_hosts',str(self.known)),('/root/.ssh',str(self.r/'ssh')),
            ('/etc/init.d/xray_rescue_tunnel',str(b/'tunnel')),('/etc/init.d/xray_rescue_watch',str(b/'watch')),('/etc/init.d/netbird',str(b/'netbird-service')),('/usr/bin/netbird',str(b/'netbird')),('/usr/bin/dbclient',str(b/'dbclient')),('/proc/uptime',str(self.uptime)),('/proc/net/tcp',str(self.proc/'net/tcp'))]:src=src.replace(old,new)
        src=src.replace("'/proc/'",repr(str(self.proc)+'/'))
        self.script=self.r/'rescue.uc';self.script.write_text(src)
        self.env=dict(os.environ,PATH=str(b)+':'+os.environ['PATH'],TEST_ROOT=str(self.r),TEST_UCI_JSON=str(self.cfg),PUBKEY=KEY)
        self.params={'action':'configure','host':'192.0.2.10','port':'62152','user':'xtls-rescue','remote_port':'22001','local_port':'222','host_key':KEY}
    def call(self,mode='action',p=None,scenario='healthy',ok=True):
        r=subprocess.run(['ucode','-L',str(self.mods),str(self.script),mode],env=dict(self.env,SCENARIO=scenario),input=json.dumps(p or self.params),capture_output=True,text=True,timeout=12)
        self.assertEqual(r.returncode==0,ok,r.stdout+r.stderr)
        self.assertNotIn('private-key-must-never-escape',r.stdout+r.stderr)
        return json.loads(r.stdout) if r.stdout else None
    def test_validated_plan_preserves_port_key_and_loopback_scope(self):
        self.call();self.call(p={'action':'open'})
        cmd=(self.run/'command.sh').read_text()
        self.assertIn('127.0.0.1:22001:127.0.0.1:222',cmd)
        for flag in ['StrictHostKeyChecking=yes','BatchMode=yes','ExitOnForwardFailure=yes','192.0.2.2']:self.assertIn(flag,cmd)
        self.assertNotIn("'-y'",cmd);self.assertNotIn('private-key',cmd)
        s=self.call('status');self.assertEqual(s['process']['pid'],123);self.assertTrue(s['process']['established'])
        self.assertEqual(s['public_key'],KEY);self.assertEqual((self.run/'command.sh').stat().st_mode&0o777,0o600)
        self.call(p={'action':'close'});self.assertFalse((self.r/'running').exists())
    def test_invalid_requests_and_host_key_conflict_leave_config_untouched(self):
        before=self.cfg.read_bytes()
        for patch in [{'host':'127.0.0.1'},{'host':'1.2.3.4;id'},{'user':'root'},{'user':'a;id'},{'port':'0'},{'remote_port':'22'},{'local_port':'65536'},{'host_key':KEY+'\ncommand=evil'}]:
            self.call(p={**self.params,**patch},ok=False);self.assertEqual(self.cfg.read_bytes(),before)
        self.known.write_text('192.0.2.10 ssh-ed25519 wrong\n');self.call(ok=False);self.assertEqual(self.cfg.read_bytes(),before)
    def test_routing_and_output_interception_refuse_start(self):
        self.call();self.call(p={'action':'open'},scenario='wrong-route',ok=False)
        d=json.loads(self.cfg.read_text());d['xray_lab_dns']['main']['output_enabled']='1';self.cfg.write_text(json.dumps(d))
        self.call(p={'action':'open'},ok=False);self.assertFalse((self.r/'running').exists())
    def test_rejection_backoff_and_disable_do_not_change_netbird(self):
        self.call();s={'outage_since':0};(self.run/'state.json').write_text(json.dumps(s))
        self.call('tick',scenario='reject');s=json.loads((self.run/'state.json').read_text());self.assertEqual(s['reason'],'start_failed');self.assertEqual(s['retry_at'],1030)
        self.call(p={'action':'disable'});self.assertEqual(self.call('status')['state']['reason'],'disabled')
        calls=[json.loads(x) for x in (self.r/'calls').read_text().splitlines()]
        self.assertFalse(any(x[0]=='netbird' and x[1]!='status' for x in calls))
        self.assertFalse(any(x[0]=='netbird-service' and x[1]!='enabled' for x in calls))
    def test_existing_identity_is_not_replaced(self):
        before=self.key.read_bytes();self.call(p={'action':'generate'});self.assertEqual(self.key.read_bytes(),before)

    def test_host_key_comment_is_preserved_without_duplicate(self):
        contents='192.0.2.10 '+KEY+' original-comment\n';self.known.write_text(contents)
        self.call();self.assertEqual(self.known.read_text(),contents)

    def test_rpc_transports_request_and_response_without_private_key(self):
        import shlex
        launcher=self.r/'launcher'
        launcher.write_text('#!/bin/sh\nexec ucode -L '+shlex.quote(str(self.mods))+' '+shlex.quote(str(self.script))+' "$@"\n');launcher.chmod(0o755)
        rpc=self.r/'rpc.uc';rpc.write_text((FILES/'usr/libexec/rpcd/xray_lab_rescue').read_text()
            .replace('/usr/bin/xray-lab-rescue',str(launcher)).replace('/var/run/xtlspro-rescue',str(self.run)))
        for method,p in [('action',self.params),('status',{}),('action',{'action':'shell;id'})]:
            r=subprocess.run(['ucode',str(rpc),'call',method],env=self.env,input=json.dumps(p),capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout)
            if method=='status':self.assertEqual(d['public_key'],KEY)
            elif p['action']=='configure':self.assertTrue(d['ok'])
            else:self.assertIn('error',d)
            self.assertNotIn('private-key-must-never-escape',r.stdout+r.stderr)
        self.assertFalse(list(self.run.glob('rpc-*.json')))

    def test_runner_executes_only_validated_arguments(self):
        self.call();self.call(p={'action':'open'})
        runner=self.r/'runner';runner.write_text((FILES/'usr/bin/xray-rescue-tunnel').read_text().replace('/var/run/xtlspro-rescue',str(self.run)))
        r=subprocess.run(['sh',str(runner)],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(r.returncode,0,r.stderr)
        calls=[json.loads(x) for x in (self.r/'calls').read_text().splitlines()]
        args=next(x for x in calls if x[0]=='dbclient')
        self.assertIn('xtls-rescue@192.0.2.10',args);self.assertIn('127.0.0.1:22001:127.0.0.1:222',args)

if __name__=='__main__':unittest.main()
