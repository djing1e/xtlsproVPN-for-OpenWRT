import base64
from contextlib import contextmanager
import copy
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import test_telegram as pilot

spec=importlib.util.spec_from_file_location('fleet',Path(__file__).resolve().parents[1]/'server/fleet.py')
f=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'bot':pilot.b}):spec.loader.exec_module(f)
DEVICE='11111111-2222-4333-8444-555555555555'
PROFILE='11111111-2222-4333-8444-555555555556'
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGvOWJsdfLieCYoFuZ9MB2UgQHh6s+0yfZm+VVdLR5Ox'
RESCUE='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMU9f6nqzVlV1VTmO9qVc7Tn2nZSse6IZCglzH6oW5RX'
P={'schema':1,'profile_id':PROFILE,'device_id':DEVICE,'host':'100.124.249.61','port':22,'model':'Same model','host_key':KEY,'rescue_public_key':RESCUE}


class FleetPlanningTests(unittest.TestCase):
    def test_code_is_public_whitelist_and_profile_is_bound(self):
        raw={**P,'subscription_url':'SECRET','private_key':'SECRET'}
        code='xtls-enroll-v1:'+base64.b64encode(json.dumps(raw).encode()).decode()
        parsed=f.passport(f.decode(code),{'profile_id':PROFILE})
        self.assertEqual(parsed,P)
        with self.assertRaises(pilot.b.SafeError):f.passport(raw,{'profile_id':DEVICE})
        for code in ('bad','xtls-enroll-v1:!'):
            with self.assertRaises(pilot.b.SafeError):f.decode(code)

    def test_same_model_gets_distinct_ids_but_uuid_and_key_duplicates_refused(self):
        config={'routers':{}}
        rid,name=f.choose(config,P)
        second={**P,'device_id':PROFILE,'host':'100.124.0.2','host_key':RESCUE}
        other,_=f.choose(config,second)
        self.assertNotEqual(rid,other)
        config['routers'][rid]={'name':name,'host':P['host'],'port':22,'device_id':DEVICE,'fleet':{'host_key':KEY}}
        self.assertEqual(f.choose(config,P)[0],rid)
        for duplicate in ({**second,'device_id':DEVICE}, {**second,'host_key':KEY}):
            with self.assertRaises(pilot.b.SafeError):f.choose(config,duplicate)

    def test_adopt_preserves_lab_mapping_and_changed_device_rejected(self):
        config={'routers':{'lab':{'name':'LAB','host':P['host'],'port':22}}}
        self.assertEqual(f.choose(config,P,'lab'),('lab','LAB'))
        config['routers']['lab']['device_id']=PROFILE
        with self.assertRaises(pilot.b.SafeError):f.choose(config,P,'lab')

    def test_primary_and_rescue_pins_idempotent_and_conflicts_rejected(self):
        pins=f.pinned('',P,22003)
        self.assertEqual(f.pinned(pins,P,22003),pins)
        with self.assertRaises(pilot.b.SafeError):f.pinned(P['host']+' '+RESCUE+'\n',P,22003)
        salt=b'01234567890123456789'
        hashed='|1|'+base64.b64encode(salt).decode()+'|'+base64.b64encode(hmac.new(salt,P['host'].encode(),hashlib.sha1).digest()).decode()
        with self.assertRaises(pilot.b.SafeError):f.pinned(hashed+' '+RESCUE+'\n',P,22003)

    def test_relay_scoped_to_one_loopback_port_and_no_shell(self):
        text=f.relay_text('xtls-r-111111112222',22003)
        for rule in ('AllowTcpForwarding remote','PermitListen 127.0.0.1:22003','PermitOpen none','GatewayPorts no','MaxSessions 0','PasswordAuthentication no'):
            self.assertIn(rule,text)
        with self.assertRaises(pilot.b.SafeError):f.relay_text('root',22003)

    def test_profile_accepts_real_keygen_comment_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config_path=root/'config.json';output=root/'profile.json'
            config={'ssh_key':'/private/bot-key','routers':{}}
            config_path.write_text(json.dumps(config))
            read=Path.read_text;mkdtemp=tempfile.mkdtemp
            def read_text(path,*args,**kwargs):
                if str(path)=='/etc/ssh/ssh_host_ed25519_key.pub':return KEY+' root@bot\n'
                return read(path,*args,**kwargs)
            with patch.object(f,'CONFIG',config_path),patch.object(f,'command',return_value=SimpleNamespace(stdout=RESCUE+' xtls-router-bot\n')),patch.object(Path,'read_text',read_text),patch.object(f.os,'chown'),patch.object(f.tempfile,'mkdtemp',side_effect=lambda **kw:mkdtemp(dir=root)):
                f.profile_command(config,'87.239.135.108',62152,output)
                value=json.loads(output.read_text())
                self.assertEqual(value['bot_public_key'],RESCUE)
                self.assertEqual(value['rescue_host_key'],KEY)
                f.profile_command(config,'87.239.135.108',62152,output)
                self.assertEqual(json.loads(output.read_text()),value)

    def test_shared_parent_traversable_under_private_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/'relay-homes'
            old=os.umask(0o077)
            try:
                f.shared_relay_homes(parent)
                self.assertEqual(parent.stat().st_mode & 0o777,0o755)
                parent.chmod(0o700)
                f.shared_relay_homes(parent)
                self.assertEqual(parent.stat().st_mode & 0o777,0o755)
            finally:os.umask(old)
            link=Path(directory)/'link';link.symlink_to(parent)
            with self.assertRaises(pilot.b.SafeError):f.shared_relay_homes(link)

    def test_retry_reuses_only_uuid_owned_orphan_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'home';home.mkdir()
            marker=home/'.xtls-fleet-device';marker.write_text(DEVICE)
            account='xtls-r-497667c61b7d'
            (root/('65-xtls-fleet-'+account+'.conf')).write_text(f.relay_text(account,22001))
            config={'routers':{'lab':{'rescue':{'port':22002}}}}
            with patch.object(f,'SSHD_DIR',root),patch.object(f.pwd,'getpwnam',return_value=SimpleNamespace(pw_dir=str(home))),patch.object(f,'free_port',return_value=22003) as allocate:
                self.assertEqual(f.enrollment_port(config,account,DEVICE),22001)
                allocate.assert_not_called()
                marker.write_text(PROFILE)
                with self.assertRaises(pilot.b.SafeError):f.enrollment_port(config,account,DEVICE)
                marker.write_text(DEVICE)
                config['routers']['other']={'rescue':{'port':22001}}
                with self.assertRaises(pilot.b.SafeError):f.enrollment_port(config,account,DEVICE)

    def test_allocator_reserves_roster_live_and_orphan_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'orphan.conf').write_text('Match User orphan\n    PermitListen 127.0.0.1:22002\n')
            sock=SimpleNamespace(__enter__=lambda s:s,__exit__=lambda *a:None)
            class Socket:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def bind(self,address):
                    if address[1]==22003:raise OSError()
            with patch.object(f,'SSHD_DIR',root),patch.object(f.socket,'socket',return_value=Socket()):
                self.assertEqual(f.free_port({'routers':{'lab':{'rescue':{'port':22001}}}}),22004)


class FleetTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config_path=self.root/'config.json';self.pins=self.root/'known_hosts';self.pins.write_text(P['host']+' '+KEY+'\n')
        self.db=self.root/'state.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.executescript('CREATE TABLE operations(state TEXT);CREATE TABLE router_ids(seq INTEGER PRIMARY KEY,router TEXT);INSERT INTO router_ids VALUES(1,"lab");CREATE TABLE grants(uid INTEGER,router TEXT);INSERT INTO grants VALUES(123,"lab");')
        self.config={'admin_id':1,'bot_username':'xtlsproroutbot','ssh_key':str(self.root/'key'),'known_hosts':str(self.pins),'database':str(self.db),'fleet_profile':{'profile_id':PROFILE},'routers':{'lab':{'host':P['host'],'port':22,'name':'LAB','rescue':{'host':'127.0.0.1','port':22002}}}}
        self.config_path.write_text(json.dumps(self.config));self.old_config=self.config_path.read_text();self.old_pins=self.pins.read_text()
        self.state=None;self.calls=[];self.commands=[];self.rescue_fails=False;self.start_fails=False;self.commit_lost=False
        def remote(config,router,pins,command,input_data=None):
            self.calls.append(command)
            if router['host']=='127.0.0.1' and self.rescue_fails:raise pilot.b.SafeError('Unreachable')
            if command=='xtlsbot-v1 admin-open-rescue':
                self.rescue_fails=False
                return {'ok':True}
            if command=='xtlsbot-v1 identity':return {**P,'enrollment':copy.deepcopy(self.state)}
            if 'enroll-apply' in command:
                self.state={'transaction':command.split()[-1],'state':'pending','user':input_data['user'],'remote_port':input_data['remote_port']}
                return {'ok':True}
            if 'enroll-commit' in command:
                self.state['state']='enrolled'
                if self.commit_lost:raise pilot.b.SafeError('Receipt lost')
                return {'ok':True}
            if 'enroll-rollback' in command:self.state['state']='rolled_back';return {'ok':True}
            raise AssertionError(command)
        def cmd(*args):
            self.commands.append(args)
            if args[:2]==('systemctl','start') and self.start_fails:
                self.start_fails=False;raise pilot.b.SafeError('Start failed')
            return SimpleNamespace(stdout='')
        @contextmanager
        def owner(*args):yield
        original_mkdtemp=tempfile.mkdtemp
        self.patchers=[patch.object(f,'CONFIG',self.config_path),patch.object(f,'remote',side_effect=remote),patch.object(f,'command',side_effect=cmd),patch.object(f,'relay'),patch.object(f,'enrollment_port',return_value=22003),patch.object(f,'db_owner',owner),patch.object(f.time,'sleep'),patch.object(f.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())),patch.object(f.tempfile,'mkdtemp',side_effect=lambda **kw:original_mkdtemp(dir=self.root,prefix='backup.'))]
        for p in self.patchers:p.start();self.addCleanup(p.stop)

    def test_enroll_and_repeat_preserve_lab_id_grants_and_ports(self):
        f.enroll(self.config,P,'lab',None)
        saved=json.loads(self.config_path.read_text())
        self.assertEqual(saved['routers']['lab']['device_id'],DEVICE)
        self.assertEqual(saved['routers']['lab']['rescue']['port'],22003)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT * FROM grants').fetchall(),[(123,'lab')])
        commands=len(self.commands)
        self.rescue_fails=True  # Standby tunnel has closed since first enrollment.
        f.enroll(saved,P,None,None)
        self.assertIn('xtlsbot-v1 admin-open-rescue',self.calls)
        self.assertFalse(self.rescue_fails)
        self.assertEqual(sum('enroll-apply' in x for x in self.calls),1)
        self.assertEqual(len(self.commands),commands)
        self.assertEqual(self.pins.read_text().count('[127.0.0.1]:22003'),1)

    def test_busy_operation_prevents_tunnel_mutation_and_broker_stop(self):
        with sqlite3.connect(self.db) as db:db.execute("INSERT INTO operations VALUES('running')")
        with self.assertRaises(pilot.b.SafeError):f.enroll(self.config,P,'lab',None)
        self.assertIsNone(self.state)
        self.assertFalse(any('enroll-apply' in call for call in self.calls))
        self.assertFalse(any(args[:2]==('systemctl','stop') for args in self.commands))

    def test_failed_rescue_rolls_router_back_before_registry_write(self):
        self.rescue_fails=True
        with patch.object(f.time,'monotonic',side_effect=[0,51]):
            with self.assertRaises(pilot.b.SafeError):f.enroll(self.config,P,'lab',None)
        self.assertEqual(self.state['state'],'rolled_back')
        self.assertEqual(self.config_path.read_text(),self.old_config);self.assertEqual(self.pins.read_text(),self.old_pins)

    def test_failed_broker_start_restores_registry_and_router(self):
        self.start_fails=True
        with self.assertRaises(pilot.b.SafeError):f.enroll(self.config,P,'lab',None)
        self.assertEqual(self.state['state'],'rolled_back')
        self.assertEqual(self.config_path.read_text(),self.old_config);self.assertEqual(self.pins.read_text(),self.old_pins)

    def test_lost_commit_receipt_is_reconciled_without_reapplying(self):
        self.commit_lost=True
        f.enroll(self.config,P,'lab',None)
        self.assertEqual(self.state['state'],'enrolled')
        self.assertEqual(sum('enroll-apply' in x for x in self.calls),1)
        self.assertIn('device_id',json.loads(self.config_path.read_text())['routers']['lab'])


class FleetRemoteBoundaryTests(unittest.TestCase):
    def test_open_rescue_crosses_real_remote_boundary(self):
        def run(args,**kwargs):
            self.assertEqual(args[-1],'xtlsbot-v1 admin-open-rescue')
            kwargs['stdout'].write(json.dumps({'schema':1,'ok':True,'data':{'ok':True}}).encode())
            return SimpleNamespace(returncode=0)
        with patch.object(f,'ssh_command',return_value=['ssh','host','xtlsbot-v1 admin-open-rescue']),patch.object(f.subprocess,'run',side_effect=run):
            self.assertEqual(f.remote({}, {}, '/tmp/pins','xtlsbot-v1 admin-open-rescue'),{'ok':True})
    def test_open_rescue_does_not_allow_arguments_or_shell_commands(self):
        for value in ['xtlsbot-v1 admin-open-rescue extra','xtlsbot-v1 admin-open-rescue; reboot','reboot']:
            with patch.object(f.subprocess,'run') as run:
                with self.assertRaises(pilot.b.SafeError):f.remote({}, {}, '/tmp/pins',value)
                run.assert_not_called()
