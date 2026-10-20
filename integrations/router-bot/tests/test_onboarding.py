import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]/'router'
DEVICE='11111111-2222-4333-8444-555555555555'
PROFILE='11111111-2222-4333-8444-555555555556'
TX='11111111-2222-4333-8444-555555555557'
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGvOWJsdfLieCYoFuZ9MB2UgQHh6s+0yfZm+VVdLR5Ox'
BOT='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMU9f6nqzVlV1VTmO9qVc7Tn2nZSse6IZCglzH6oW5RX'


@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class OnboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.dest=self.root/'private';self.dest.mkdir()
        self.config=self.root/'rescue.config';self.config.write_text('ORIGINAL CONFIG')
        self.uuid=self.root/'uuid';self.uuid.write_text(DEVICE+'\n')
        self.profile={'schema':1,'profile_id':PROFILE,'bot_public_key':BOT,'rescue_host':'87.239.135.108','rescue_port':62152,'rescue_host_key':KEY}
        self.input=self.root/'profile.json';self.input.write_text(json.dumps(self.profile))
        self.fixture=self.root/'fixture.json';self.fixture.write_text(json.dumps({'ports':[22]}))
        self.mods=self.root/'mods';self.mods.mkdir()
        (self.mods/'uci.uc').write_text('''import * as fs from 'fs';
export function cursor(){return {get_all:function(name){let f=json(fs.readfile(getenv('ONBOARD_FIXTURE')));let d={};for(let p in f.ports)d['port'+p]={'.type':'dropbear',Port:''+p};return d;}};};
''')
        self.bins=self.root/'bin';self.bins.mkdir()
        self.log=self.root/'actions';self.bad=self.root/'fail-open'
        self.make('dropbearkey',"echo 'Public key portion is:'\necho '"+KEY+" fixture'")
        self.make('ubus',"echo '{\"model\":\"Cudy duplicate model\",\"secret\":\"SECRET-BOARD\"}'")
        self.make('netbird',"echo '{\"netbird_ip\":\"100.124.249.61/16\",\"management_url\":\"SECRET-URL\"}'")
        self.make('uci','echo 0')
        self.make('service','exit 0')
        self.make('rescue','''exec python3 - <<'END'
END''')
        rescue=self.bins/'rescue'
        rescue.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
p=json.load(sys.stdin)
with open('''+repr(str(self.log))+''','a') as f:f.write(json.dumps(p)+'\\n')
if p['action']=='configure':Path('''+repr(str(self.config))+''').write_text('CHANGED')
if p['action']=='open' and Path('''+repr(str(self.bad))+''').exists():print('{"error":"failed"}')
else:print('{"ok":true}')
''');rescue.chmod(0o700)
        source=(BASE/'onboard.uc').read_text().replace('/etc/xtlspro-bot',str(self.dest)).replace('/etc/config/xray_lab_rescue',str(self.config)).replace('/proc/sys/kernel/random/uuid',str(self.uuid)).replace('/usr/bin/dropbearkey',str(self.bins/'dropbearkey')).replace('/usr/bin/xray-lab-netbird',str(self.bins/'netbird')).replace('/usr/bin/xray-lab-rescue',str(self.bins/'rescue')).replace('/etc/init.d/xray_rescue_tunnel',str(self.bins/'service')).replace('/etc/init.d/xray_rescue_watch',str(self.bins/'service'))
        self.source=self.root/'onboard.uc';self.source.write_text(source)
        self.env=dict(os.environ,PATH=str(self.bins)+':'+os.environ['PATH'],ONBOARD_FIXTURE=str(self.fixture))

    def make(self,name,text):
        p=self.bins/name;p.write_text('#!/bin/sh\n'+text+'\n');p.chmod(0o700)

    def call(self,*args,payload=None):
        r=subprocess.run(['ucode','-L',str(self.mods),str(self.source),*args],input=json.dumps(payload) if payload is not None else '',env=self.env,capture_output=True,text=True,timeout=15)
        self.assertNotIn('SECRET',r.stdout)
        return r,json.loads(r.stdout) if r.stdout else None

    def prepare(self):
        result,data=self.call('prepare',str(self.input));self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return data

    def request(self):
        return {'profile_id':PROFILE,'transaction':TX,'user':'xtls-r-111111112222','remote_port':22003,'local_port':22}

    def test_prepare_persists_uuid_and_passport_contains_only_public_fields(self):
        self.prepare();self.uuid.write_text(PROFILE)
        self.assertEqual(self.prepare()['device_id'],DEVICE)
        result,data=self.call('passport')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(set(data),{'schema','profile_id','device_id','model','host','port','host_key','rescue_public_key','enrollment'})
        self.assertEqual(data['host_key'],KEY);self.assertEqual(data['port'],22)
        self.assertEqual((self.dest/'profile.json').stat().st_mode&0o777,0o600)

    def test_profile_change_refused_without_touching_binding(self):
        self.prepare();self.profile['rescue_host']='1.1.1.1';self.input.write_text(json.dumps(self.profile))
        result,data=self.call('prepare',str(self.input));self.assertNotEqual(result.returncode,0)
        self.assertEqual(data['error'],'profile_change_requires_migration')
        self.assertEqual(json.loads((self.dest/'profile.json').read_text())['rescue_host'],'87.239.135.108')

    def test_apply_commit_and_duplicate_do_not_rotate_identity(self):
        self.prepare()
        result,data=self.call('apply',DEVICE,TX,payload=self.request())
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertEqual(data['state'],'pending')
        self.assertEqual(self.call('commit',DEVICE,TX)[1]['state'],'enrolled')
        self.assertEqual(self.call('apply',DEVICE,TX,payload=self.request())[1]['state'],'enrolled')
        self.assertEqual(self.log.read_text().count('"action": "configure"'),1)
        self.assertEqual(self.call('identity')[1]['enrollment']['state'],'enrolled')

    def test_failed_open_restores_previous_rescue_configuration(self):
        self.prepare();self.bad.touch()
        result,data=self.call('apply',DEVICE,TX,payload=self.request())
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.config.read_text(),'ORIGINAL CONFIG')
        self.assertEqual(json.loads((self.dest/'enrollment.json').read_text())['state'],'rolled_back')

    def test_pending_can_rollback_but_committed_cannot(self):
        self.prepare();self.call('apply',DEVICE,TX,payload=self.request())
        self.assertEqual(self.call('rollback',DEVICE,TX)[1]['state'],'rolled_back')
        self.assertEqual(self.config.read_text(),'ORIGINAL CONFIG')

    def test_wrong_device_profile_port_or_account_rejected_before_action(self):
        self.prepare()
        for field,value in [('profile_id',DEVICE),('local_port',80),('remote_port',22),('user','root')]:
            data=self.request();data[field]=value
            result,reply=self.call('apply',DEVICE,TX,payload=data)
            self.assertNotEqual(result.returncode,0,(field,result.stdout+result.stderr))
        self.assertFalse(self.log.exists())
        self.assertNotEqual(self.call('apply',PROFILE,TX,payload=self.request())[0].returncode,0)

    def test_multiple_ssh_ports_refused(self):
        self.prepare();self.fixture.write_text(json.dumps({'ports':[22,222]}))
        self.assertEqual(self.call('passport')[1]['error'],'ambiguous_ssh_port')
