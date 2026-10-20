import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
JOB='11111111-2222-4333-8444-555555555555'

@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class Bridge(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.r=Path(self.tmp.name);self.log=self.r/'calls'
        self.env=dict(os.environ,BRIDGE_CALLS=str(self.log),BRIDGE_FIXTURE=str(self.r/'fixture.json'))
        self.fixture={'version':'1.3.0-r4','enabled':True,'mode':'auto','core':{'running':True},
            'health':{'proxy_ok':True,'checked':100},'job':{'state':'idle'},'operation_busy':False,
            'subscription':{'url':'SECRET-SUBSCRIPTION'},'nodes':[
                {'id':'cfg123456','name':'SECRET-ENDPOINT','selected':True,'alive':True,'rtt_ms':123},
                {'id':'cfgabcdef','name':'SECRET-ENDPOINT','selected':False,'alive':None}],
            'uci':{'cfg123456':{'alias':'Finland','password':'SECRET-CREDENTIAL'},'cfgabcdef':{}}}
        mods=self.r/'modules';mods.mkdir()
        (mods/'uci.uc').write_text('''import * as fs from 'fs';
export function cursor(){return {load:function(){return true;},get_all:function(name){let f=json(fs.readfile(getenv('BRIDGE_FIXTURE')));return name=='forkop_xray'?(f.hwid_settings || {}):f.uci;}};};
''')
        ctl=self.r/'controller'
        ctl.write_text('''#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
a=sys.argv[1:];f=json.loads(Path(os.environ['BRIDGE_FIXTURE']).read_text())
with open(os.environ['BRIDGE_CALLS'],'a') as p:p.write(json.dumps(a)+'\\n')
if a==['status']:print(json.dumps(f))
elif a==['job']:print(json.dumps(f.get('last_job',{'id':'11111111-2222-4333-8444-555555555555','state':'done','action':'select'})))
elif a[:2]==['launch','select']:print(json.dumps(f.get('launch',{'id':'11111111-2222-4333-8444-555555555555','state':'pending','action':'select'})))
else:sys.exit(1)
''');ctl.chmod(0o700)
        admin=self.r/'admin'
        admin.write_text('''#!/usr/bin/env python3
import json,sys,os
with open(os.environ['BRIDGE_CALLS'],'a') as p:p.write(json.dumps(['admin',*sys.argv[1:]])+'\\n')
print(json.dumps({'boot_id':'11111111-2222-4333-8444-555555555555','job':{'state':'idle'}} if sys.argv[1:] == ['status'] else {'accepted':True,'id':sys.argv[-1],'action':sys.argv[-2]}))
''');admin.chmod(0o700)
        updates=self.r/'updates'
        updates.write_text('''#!/usr/bin/env python3
import json,sys,os
with open(os.environ['BRIDGE_CALLS'],'a') as p:p.write(json.dumps(['updates',*sys.argv[1:]])+'\\n')
print(json.dumps({'plans':[],'job':{'state':'idle'}} if sys.argv[1:] == ['status'] else {'accepted':True,'id':sys.argv[4],'action':sys.argv[2],'component':sys.argv[3]}))
''');updates.chmod(0o700)
        onboard=self.r/'onboard.uc'
        onboard.write_text("import * as fs from 'fs';printf('%J\\n',{args:ARGV,input:json(fs.stdin.read(4097) || '{}')});")
        self.onboard=onboard
        self.src=self.r/'ssh.uc';self.src.write_text((BASE/'router/ssh.uc').read_text().replace('/usr/bin/xray-lab-control',str(ctl)).replace('/etc/xtlspro-bot/admin-worker',str(admin)).replace('/etc/xtlspro-bot/update-worker',str(updates)).replace('/etc/xtlspro-bot/onboard.uc',str(onboard)).replace('/usr/bin/ucode',shutil.which('ucode')).replace('/etc/forkop-xray/device-hwid-short',str(self.r/'hwid')))
        self.mods=mods
    def call(self,cmd,ok=True,input_data=None):
        (self.r/'fixture.json').write_text(json.dumps(self.fixture))
        r=subprocess.run(['ucode','-L',str(self.mods),str(self.src)],env=dict(self.env,SSH_ORIGINAL_COMMAND=cmd),capture_output=True,text=True,timeout=10,input=input_data)
        self.assertEqual(r.returncode==0,ok,r.stdout+r.stderr)
        self.assertNotIn('SECRET-',r.stdout+r.stderr)
        d=json.loads(r.stdout);self.assertEqual(d['schema'],1);self.assertEqual(d['ok'],ok)
        return d
    def test_enrollment_closed_commands_and_stdin_quoting(self):
        self.assertIn('args',self.call('xtlsbot-v1 identity')['data'])
        value={"label":"a'$(touch /tmp/xtls-injection-never);b"}
        d=self.call('xtlsbot-v1 enroll-apply '+JOB+' '+JOB,input_data=json.dumps(value))['data']
        self.assertEqual(d['args'],['apply',JOB,JOB]);self.assertEqual(d['input'],value)
        self.assertFalse(Path('/tmp/xtls-injection-never').exists())
        self.assertEqual(self.call('xtlsbot-v1 enroll-commit '+JOB+' '+JOB)['data']['args'],['commit',JOB,JOB])
    def test_enrollment_rejects_bad_payload_and_command(self):
        command='xtlsbot-v1 enroll-apply '+JOB+' '+JOB
        for body in ['[]','not-json','x'*4097]:self.call(command,False,input_data=body)
        for bad in [command+';id',command+' extra','xtlsbot-v1 enroll-commit bad '+JOB]:self.call(bad,False)
    def test_admin_commands_use_fixed_helper_without_native_selection(self):
        data=self.call('xtlsbot-v1 admin-status')['data']
        self.assertEqual(data['job']['state'],'idle')
        data=self.call('xtlsbot-v1 admin netbird '+JOB)['data']
        self.assertTrue(data['accepted'])
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1]),['admin','launch','netbird',JOB])
    def test_admin_command_injection_never_reaches_helper(self):
        for cmd in ['xtlsbot-v1 admin shell '+JOB, 'xtlsbot-v1 admin reboot '+JOB+';id', 'xtlsbot-v1 admin reboot invalid', 'xtlsbot-v1 admin-status ', 'xtlsbot-v1 admin-open-rescue extra']:
            self.assertEqual(self.call(cmd,False)['error']['code'],'unsupported_command')
        self.assertFalse(self.log.exists())
    def test_update_protocol_binds_component_request_and_plan(self):
        self.assertEqual(self.call('xtlsbot-v1 updates')['data']['plans'],[])
        self.call('xtlsbot-v1 update-check app '+JOB)
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1]),['updates','launch','check','app',JOB,JOB])
        plan='00000000-2222-4333-8444-555555555555'
        data=self.call('xtlsbot-v1 update-install netbird '+JOB+' '+plan)['data']
        self.assertEqual(data['id'],JOB)
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1]),['updates','launch','install','netbird',JOB,plan])
    def test_bad_update_protocol_never_reaches_helper(self):
        for cmd in ['xtlsbot-v1 update-install app '+JOB,'xtlsbot-v1 update-check app '+JOB+' '+JOB,'xtlsbot-v1 update-check firmware '+JOB,'xtlsbot-v1 update-install app '+JOB+' https://SECRET-URL','xtlsbot-v1 update-check netbird '+JOB+';id']:
            self.assertEqual(self.call(cmd,False)['error']['code'],'unsupported_command')
        self.assertFalse(self.log.exists())
    def test_status_only_exports_whitelist(self):
        d=self.call('xtlsbot-v1 status')['data']
        self.assertTrue(d['running']);self.assertEqual(d['selected'],['cfg123456'])
        self.assertEqual(set(d),{'version','enabled','running','mode','selected','proxy_ok','health_checked','operation_busy','hwid','subscription','job'})
    def test_hwid_uses_same_saved_identity_and_never_generates_one(self):
        self.fixture['hwid_settings']={'hwid_enabled':'1'}
        self.assertIsNone(self.call('xtlsbot-v1 status')['data']['hwid'])
        self.assertFalse((self.r/'hwid').exists())
        (self.r/'hwid').write_text('abcd-1234-5678-90ef\n')
        self.assertEqual(self.call('xtlsbot-v1 status')['data']['hwid'],'abcd-1234-5678-90ef')
        self.assertEqual((self.r/'hwid').read_text(),'abcd-1234-5678-90ef\n')
    def test_hwid_is_actual_custom_header_without_other_settings(self):
        self.fixture['hwid_settings']={'hwid_enabled':'1','hwid':'abcd-1234-5678-90ef','subscription_url':'SECRET-URL'}
        self.assertEqual(self.call('xtlsbot-v1 status')['data']['hwid'],'abcd-1234-5678-90ef')
        self.fixture['hwid_settings']['hwid_enabled']='0'
        self.assertIsNone(self.call('xtlsbot-v1 status')['data']['hwid'])
        self.fixture['hwid_settings']={'hwid':'invalid\nSECRET-URL'}
        self.assertIsNone(self.call('xtlsbot-v1 status')['data']['hwid'])
    def test_subscription_only_numeric_id_dates_and_counters(self):
        self.fixture['subscription']={'announce':'id: 4242','title':'SECRET-TITLE',
            'url':'SECRET-URL','available':True,'updated':100,'expire':200,
            'traffic':{'used':123,'total':None,'unlimited':True,'nested':'SECRET-EXTRA'}}
        sub=self.call('xtlsbot-v1 status')['data']['subscription']
        self.assertEqual(sub['id'],'4242');self.assertEqual(sub['used'],123)
        self.assertTrue(sub['unlimited']);self.assertNotIn('title',sub)
        for raw in ['id: 4242 https://SECRET-URL', 'SECRET-URL', 'id: 4242\nSECRET-URL']:
            self.fixture['subscription']['announce']=raw
            self.assertIsNone(self.call('xtlsbot-v1 status')['data']['subscription']['id'])
    def test_diagnostics_exports_no_addresses_routes_or_config(self):
        self.fixture.update({'uptime':123,'memory':{'total':1024,'available':512},
            'interface':{'up':True,'address':'SECRET-LAN'},'interception':{'active':True},
            'diagnostics_summary':{'errors':0,'pending':0,'raw':'SECRET-LOG'}})
        d=self.call('xtlsbot-v1 diagnostics')['data']
        self.assertEqual(d['uptime'],123);self.assertTrue(d['interface_up'])
        self.assertEqual(d['errors'],0)
    def test_locations_never_fall_back_to_endpoint(self):
        nodes=self.call('xtlsbot-v1 locations')['data']['nodes']
        self.assertEqual([n['name'] for n in nodes],['Finland','Location 2'])
        self.assertEqual(set(nodes[0]),{'id','name','selected','alive','rtt_ms'})
    def test_unknown_commands_never_reach_controller(self):
        for cmd in ['', 'sh','id','sftp','xtlsbot-v1 status;id','xtlsbot-v1 status\nid',
                    'xtlsbot-v1 status\n','xtlsbot-v1 status ','xtlsbot-v1 select cfg123456 extra',
                    'xtlsbot-v1 select $(id)','xtlsbot-v1 select cfg12345/', 'xtlsbot-v1 auto\r', 'x'*121]:
            with self.subTest(cmd=cmd):self.assertEqual(self.call(cmd,False)['error']['code'],'unsupported_command')
        self.assertFalse(self.log.exists())
    def test_select_is_async_and_uses_existing_launcher(self):
        d=self.call('xtlsbot-v1 select cfgabcdef')['data']
        self.assertTrue(d['accepted']);self.assertEqual(d['job']['state'],'pending')
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1]),['launch','select','cfgabcdef'])
    def test_auto_uses_existing_launcher(self):
        self.call('xtlsbot-v1 auto')
        self.assertEqual(json.loads(self.log.read_text().splitlines()[-1]),['launch','select','auto'])
    def test_unknown_location_and_offline_refused(self):
        self.assertEqual(self.call('xtlsbot-v1 select cfg000000',False)['error']['code'],'unknown_location')
        self.fixture['core']['running']=False
        self.assertEqual(self.call('xtlsbot-v1 auto',False)['error']['code'],'proxy_not_running')
        self.assertFalse(any(json.loads(x)[0]=='launch' for x in self.log.read_text().splitlines()))
    def test_busy_and_launcher_rejection(self):
        self.fixture['operation_busy']=True
        self.assertEqual(self.call('xtlsbot-v1 auto',False)['error']['code'],'busy')
        self.fixture['operation_busy']=False;self.fixture['launch']={'error':'SECRET-INTERNAL-DETAILS'}
        self.assertEqual(self.call('xtlsbot-v1 auto',False)['error']['code'],'operation_rejected')
    def test_job_requires_matching_receipt(self):
        self.assertEqual(self.call('xtlsbot-v1 job '+JOB)['data']['job']['state'],'done')
        self.fixture['last_job']={'id':'00000000-2222-4333-8444-555555555555','state':'done','message':'SECRET-LOG'}
        self.assertEqual(self.call('xtlsbot-v1 job '+JOB,False)['error']['code'],'job_replaced')

if __name__=='__main__':unittest.main()
