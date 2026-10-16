import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'package/xtlsprovpn/files'
KEY = '11111111-2222-4333-8444-555555555555'
FLAGS = ['--disable-dns', '--disable-client-routes', '--disable-server-routes',
         '--interface-name', '--allow-server-ssh', '--setup-key-file', '--disable-auto-connect']
UCI = r"""
let fs=require('fs');
export function cursor() {
 let path=getenv('TEST_UCI_JSON'),data=json(fs.readfile(path));
 return {
  get_all:function(p,s){return s?data[p]?.[s]:data[p];},
  set:function(p,s,k,v){
   data[p] ||= {};
   if (v==null) data[p][s]={'.type':k};
   else {data[p][s] ||= {};data[p][s][k]=v;}
   return true;
  },
  delete:function(p,s,k){if(k)delete data[p][s][k];else delete data[p][s];return true;},
  commit:function(p){return !!fs.writefile(path,sprintf('%J',data));}
 };
};
"""
MOCK = r"""#!/usr/bin/env python3
import hashlib,json,os,stat,sys,time
from pathlib import Path
r=Path(os.environ['TEST_ROOT']); name=Path(sys.argv[0]).name; args=sys.argv[1:]
with (r/'calls').open('a') as f:f.write(json.dumps([name,*args])+'\n')
scenario=os.environ.get('SCENARIO','ok')
if name=='netbird':
 if args==['up','--help']:
  print(os.environ['TEST_FLAGS'] if scenario!='old-client' else '--management-url')
 elif args==['status','--json']:
  connected=(r/'connected').exists()
  print(json.dumps({'management':{'connected':connected,'url':'https://nb.example.test:443'},'signal':{'connected':connected},
    'netbirdIp':'100.100.0.5/16' if connected else '', 'daemonVersion':'0.66.0',
    'setupKey':'must-not-be-exported','peers':{'details':[{'secret':'not-returned'}]}}))
 elif args==['down']:
  (r/'connected').unlink(missing_ok=True)
 elif args[0]=='up':
  if scenario=='slow-up':time.sleep(1)
  if '--setup-key-file' in args:
   p=Path(args[args.index('--setup-key-file')+1])
   assert stat.S_IMODE(p.stat().st_mode)==0o600
   (r/'key-hash').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
  if scenario=='failed-connect':
   print('failed setup key='+os.environ['TEST_KEY'],file=sys.stderr);sys.exit(1)
  if scenario=='failed-tls':
   print('x509: certificate signed by unknown authority',file=sys.stderr);sys.exit(1)
  if scenario=='failed-dns':
   print('lookup nb.example.test: no such host',file=sys.stderr);sys.exit(1)
  (r/'connected').touch()
elif name=='pidof':
 print('1234')
else:
 if name=='apk' and scenario=='failed-install':sys.exit(1)
 if name=='apk' and args==['add','netbird']:
  binary=r/'bin/netbird';binary.write_text(Path(sys.argv[0]).read_text());binary.chmod(0o755)
 if name=='netbird-service' and args==['enabled']:
  sys.exit(0 if (r/'enabled').exists() else 1)
 if name=='netbird-service' and args==['enable']:(r/'enabled').touch()
 if name=='netbird-service' and args==['disable']:(r/'enabled').unlink(missing_ok=True)
 if name=='firewall' and scenario=='failed-firewall':sys.exit(1)
"""


@unittest.skipUnless(shutil.which('ucode'), 'ucode runtime required')
class NetBird(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.r = Path(self.temp.name)
        self.run = self.r / 'run'
        self.run.mkdir()
        self.bin = self.r / 'bin'
        self.bin.mkdir()
        self.modules = self.r / 'modules'
        self.modules.mkdir()
        (self.modules / 'uci.uc').write_text(UCI)
        self.config = self.r / 'uci.json'
        self.original = {
            'xray_lab_netbird': {'main': {'.type':'support','enabled':'0','management_url':'','hostname':''}},
            'firewall': {'lan': {'.type':'zone','name':'lan','network':['lan'],'input':'ACCEPT'}},
            'network': {'lan': {'device':'br-lan'}},
            'dhcp': {'main': {'server':['127.0.0.1#5300']}},
            'xray_core': {'general': {'transparent_proxy_enable':'1'}}
        }
        self.config.write_text(json.dumps(self.original))
        for name in ['netbird','netbird-service','guard','firewall','apk','pidof']:
            p=self.bin/name;p.write_text(MOCK);p.chmod(0o755)
        self.script=self.r/'netbird.uc'
        source=(FILES/'usr/share/xray/lab/netbird.uc').read_text()
        source=source.replace('/var/run/xtlspro-netbird',str(self.run))
        source=source.replace('/usr/bin/netbird',str(self.bin/'netbird'))
        source=source.replace('/etc/init.d/netbird',str(self.bin/'netbird-service'))
        source=source.replace('/etc/init.d/xray_netbird_guard',str(self.bin/'guard'))
        source=source.replace('/etc/init.d/firewall',str(self.bin/'firewall'))
        source=source.replace("'/proc/'+pid", "'"+str(self.r/'proc')+"/'+pid")
        self.script.write_text(source)
        self.env=dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'],
                      TEST_ROOT=str(self.r),TEST_UCI_JSON=str(self.config),
                      TEST_FLAGS=' '.join(FLAGS),TEST_KEY=KEY)
        self.params={'management_url':'https://nb.example.test:443',
                     'hostname':'router-01','setup_key':KEY}

    def call(self,*args,input=None,env=None):
        return subprocess.run(['ucode','-L',str(self.modules),str(self.script),*args],
                              input=json.dumps(input) if input is not None else None,
                              env=env or self.env,capture_output=True,text=True,timeout=10)

    def stage(self,action='connect',params=None):
        r=self.call('stage',action,input=params if params is not None else self.params)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((self.run/'request.json').stat().st_mode&0o777,0o600)

    def worker(self, action='connect', scenario='ok'):
        return self.call('worker',action,env=dict(self.env,SCENARIO=scenario))

    def calls(self):
        p=self.r/'calls'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def job(self):
        return json.loads((self.run/'job.json').read_text())

    def test_connect_disables_dns_routes_and_builtin_ssh(self):
        self.stage()
        r=self.worker()
        self.assertEqual(r.returncode,0,r.stderr+str(self.job()))
        self.assertEqual(self.job()['state'],'done')
        up=next(a for a in self.calls() if a[:2]==['netbird','up'] and '--help' not in a)
        for flag in ['--disable-dns=true','--disable-client-routes=true',
                     '--disable-server-routes=true','--allow-server-ssh=false',
                     '--disable-auto-connect=false']:
            self.assertIn(flag,up)
        self.assertNotIn(KEY,json.dumps(self.calls()))
        self.assertIn('--setup-key-file',up)
        self.assertEqual((self.r/'key-hash').read_text(),hashlib.sha256(KEY.encode()).hexdigest())
        self.assertFalse((self.run/'request.json').exists())
        self.assertFalse((self.run/'setup.key').exists())
        saved=json.loads(self.config.read_text())
        self.assertNotIn(KEY,self.config.read_text())
        for field in ['network','dhcp','xray_core']:
            self.assertEqual(saved[field],self.original[field])
        self.assertEqual(saved['firewall']['xtlspro_netbird']['forward'],'REJECT')
        self.assertEqual(saved['firewall']['xtlspro_netbird_admin']['dest_port'],'22 80 443')
        self.assertIn(['netbird-service','enable'],self.calls())
        result=self.call('status')
        self.assertEqual(result.returncode,0,result.stderr)
        status=json.loads(result.stdout)
        self.assertTrue(status['connected'])
        self.assertNotIn('must-not-be-exported',result.stdout)
        self.assertNotIn('not-returned',result.stdout)

    def test_existing_zone_not_changed(self):
        original=self.original.copy()
        original['firewall']['existing']={'.type':'zone','device':['wt0'],'input':'REJECT'}
        self.config.write_text(json.dumps(original))
        self.stage();r=self.worker()
        self.assertEqual(r.returncode,0,r.stderr+str(self.job()))
        saved=json.loads(self.config.read_text())
        self.assertEqual(saved['firewall'],original['firewall'])
        self.assertEqual(saved['xray_lab_netbird']['main']['firewall_mode'],'existing')

    def test_failure_does_not_leak_key_or_change_firewall(self):
        self.stage();r=self.worker(scenario='failed-connect')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn(KEY,r.stdout+r.stderr+(self.run/'job.json').read_text())
        self.assertIn('Сервер отклонил регистрацию',self.job()['message'])
        self.assertFalse((self.run/'setup.key').exists())
        self.assertFalse((self.run/'request.json').exists())
        self.assertEqual(json.loads(self.config.read_text()),self.original)

    def test_login_diagnostics_classify_stderr(self):
        for scenario,message in [('failed-tls','TLS-сертификата'),('failed-dns','DNS-имя')]:
            self.stage();r=self.worker(scenario=scenario)
            self.assertNotEqual(r.returncode,0)
            self.assertIn(message,self.job()['message'])
            self.assertNotIn(KEY,json.dumps(self.job()))

    def test_missing_flags_refused_before_down(self):
        self.stage();r=self.worker(scenario='old-client')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn(['netbird','down'],self.calls())

    def test_first_registration_without_key_refused_before_down(self):
        p=dict(self.params,setup_key='')
        r=self.call('stage','connect',input=p)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('Setup key',json.loads(r.stdout)['error'])
        self.assertFalse((self.run/'request.json').exists())
        self.assertNotIn(['netbird','down'],self.calls())

    def test_registered_reconnect_without_key(self):
        self.stage();self.assertEqual(self.worker().returncode,0)
        self.stage('disconnect');self.assertEqual(self.worker('disconnect').returncode,0)
        self.stage(params=dict(self.params,setup_key=''))
        r=self.worker()
        self.assertEqual(r.returncode,0,r.stderr+str(self.job()))
        calls=[a for a in self.calls() if a[:2]==['netbird','up'] and '--help' not in a]
        self.assertNotIn('--setup-key-file',calls[-1])

    def test_new_server_without_key_does_not_disconnect_existing_peer(self):
        self.stage();self.assertEqual(self.worker().returncode,0)
        before=len(self.calls())
        r=self.call('stage','connect',input=dict(self.params,setup_key='',management_url='https://other.test'))
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn(['netbird','down'],self.calls()[before:])

    def test_existing_connected_peer_can_be_adopted_without_new_key(self):
        (self.r/'connected').touch()
        self.stage(params=dict(self.params,setup_key=''))
        r=self.worker()
        self.assertEqual(r.returncode,0,r.stderr+str(self.job()))

    def test_bad_parameters_do_not_start_commands(self):
        for field,bad in [('management_url','https://nb.test;touch /tmp/pwned'),
                          ('management_url','http://nb.test'),
                          ('management_url','https://user:pass@nb.test'),
                          ('management_url','https://nb.test:70000'),
                          ('setup_key',"x'; echo secret"),
                          ('hostname','router$(id)')]:
            p=dict(self.params);p[field]=bad
            r=self.call('stage','connect',input=p)
            self.assertNotEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertFalse((self.run/'request.json').exists())
        self.assertEqual(self.calls(),[])

    def test_existing_install_is_noop(self):
        self.stage('install')
        r=self.worker('install')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.calls(),[])

    def test_fresh_install_does_not_register_or_start_client(self):
        (self.bin/'netbird').unlink()
        self.stage('install');r=self.worker('install')
        self.assertEqual(r.returncode,0,r.stderr+str(self.job()))
        self.assertEqual(self.calls(),[['apk','update'],['apk','add','netbird']])

    def test_failed_install_reports_error(self):
        (self.bin/'netbird').unlink()
        self.stage('install');r=self.worker('install',scenario='failed-install')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.job()['state'],'failed')
        self.assertEqual(json.loads(self.config.read_text()),self.original)

    def test_existing_zone_via_network_is_reused(self):
        self.original['network']['nb']={'device':'wt0'}
        self.original['firewall']['nb']={'.type':'zone','network':['nb'],'input':'ACCEPT'}
        self.config.write_text(json.dumps(self.original))
        self.stage();r=self.worker()
        self.assertEqual(r.returncode,0,r.stderr+str(self.job()))
        self.assertEqual(json.loads(self.config.read_text())['firewall'],self.original['firewall'])

    def test_stale_job_cleans_leftover_secret(self):
        self.stage()
        (self.run/'job.json').write_text(json.dumps({'state':'pending','updated':0,'action':'connect'}))
        (self.run/'setup.key').write_text(KEY)
        r=self.call('status')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['job']['state'],'failed')
        self.assertFalse((self.run/'setup.key').exists())
        self.assertFalse((self.run/'request.json').exists())

    def test_resource_report_reads_binary_cmdline_and_rss(self):
        proc=self.r/'proc/1234';proc.mkdir(parents=True)
        (proc/'cmdline').write_bytes(b'netbird\x00service\x00run\x00')
        (proc/'status').write_text('Name:\tnetbird\nVmRSS:\t12345 kB\n')
        r=self.call('status')
        self.assertEqual(r.returncode,0,r.stderr)
        resources=json.loads(r.stdout)['resources']
        self.assertEqual(resources['pid'],1234)
        self.assertEqual(resources['rss_bytes'],12345*1024)

    def test_disconnect_keeps_identity_and_does_not_touch_xray(self):
        self.stage('disconnect');r=self.worker('disconnect')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn(['netbird-service','disable'],self.calls())
        self.assertIn(['guard','stop'],self.calls())
        self.assertEqual(json.loads(self.config.read_text()),self.original)

    def test_firewall_failure_rolls_back_only_owned_sections(self):
        self.stage();r=self.worker(scenario='failed-firewall')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(json.loads(self.config.read_text())['firewall'],self.original['firewall'])
        self.assertNotIn(['netbird-service','enable'],self.calls())

    def test_busy_launch_and_background_job(self):
        # Exercise the real shell launcher and inherited flock, not a fake lock.
        launcher=self.r/'launcher'
        launcher.write_text((FILES/'usr/bin/xray-lab-netbird').read_text()
                           .replace('/var/run/xtlspro-netbird',str(self.run))
                           .replace('/usr/share/xray/lab/netbird.uc',str(self.script))
                           .replace('ucode "$LIB"', 'ucode -L '+str(self.modules)+' "$LIB"'))
        launcher.chmod(0o755)
        env=dict(self.env,SCENARIO='slow-up')
        first=subprocess.run([str(launcher),'launch','connect'],input=json.dumps(self.params),
                             env=env,capture_output=True,text=True,timeout=3)
        self.assertTrue(json.loads(first.stdout)['ok'],first.stderr)
        second=subprocess.run([str(launcher),'launch','disconnect'],input='{}',
                              env=env,capture_output=True,text=True,timeout=3)
        self.assertIn('error',json.loads(second.stdout))
        for _ in range(60):
            if self.job()['state'] in ['done','failed']:break
            time.sleep(.05)
        self.assertEqual(self.job()['state'],'done',self.job())

    def test_rpc_passes_key_by_stdin_and_returns_json(self):
        launcher=self.r/'launcher'
        launcher.write_text((FILES/'usr/bin/xray-lab-netbird').read_text()
                           .replace('/var/run/xtlspro-netbird',str(self.run))
                           .replace('/usr/share/xray/lab/netbird.uc',str(self.script))
                           .replace('ucode "$LIB"', 'ucode -L '+str(self.modules)+' "$LIB"'))
        launcher.chmod(0o755)
        rpc=self.r/'rpc.uc'
        rpc.write_text((FILES/'usr/libexec/rpcd/xray_lab_netbird').read_text()
                       .replace('/usr/bin/xray-lab-netbird',str(launcher))
                       .replace('/var/run/xtlspro-netbird',str(self.run)))
        result=subprocess.run(['ucode',str(rpc),'call','action'],
                              input=json.dumps(dict(self.params,action='connect')),
                              env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'ok':True})
        self.assertEqual(list(self.run.glob('rpc-*.json')),[])
        for _ in range(60):
            if self.job()['state'] in ['done','failed']:break
            time.sleep(.05)
        self.assertEqual(self.job()['state'],'done',self.job())
        self.assertNotIn(KEY,result.stdout+result.stderr+json.dumps(self.calls()))

    def test_guard_only_recovers_missing_daemon_when_enabled(self):
        mock="""#!/bin/sh
case "${0##*/}" in
uci) echo "$TEST_ENABLED" ;;
pidof) exit "$TEST_PID_RC" ;;
netbird-service) echo "$*" >> "$TEST_CALLS" ;;
esac
"""
        for name in ['uci','pidof','netbird-service']:
            path=self.bin/name;path.write_text(mock);path.chmod(0o755)
        guard=self.r/'watch.sh'
        guard.write_text((FILES/'usr/bin/xray-netbird-guard').read_text()
                         .replace('/etc/init.d/netbird',str(self.bin/'netbird-service'))
                         .replace('sleep 30','exit 0'))
        for enabled,pid_rc,should_start in [('1','1',True),('1','0',False),('0','1',False)]:
            calls=self.r/'guard-calls';calls.unlink(missing_ok=True)
            r=subprocess.run(['sh',str(guard)],env=dict(self.env,TEST_ENABLED=enabled,
                             TEST_PID_RC=pid_rc,TEST_CALLS=str(calls)),capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            log=calls.read_text() if calls.exists() else ''
            self.assertEqual('start' in log,should_start)


if __name__=='__main__':
    unittest.main()
