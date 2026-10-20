import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_telegram as pilot
import test_fleet as ft
import test_connect as ct
import test_backup as bt

SERVER=Path(__file__).resolve().parents[1]/'server'
def module(name):
    spec=importlib.util.spec_from_file_location(name,SERVER/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
client=module('operator_client')
with patch.dict(sys.modules,{'backup':bt.backup,'connect':ct.c,'fleet':ft.f,'bot':pilot.b,'operator_client':client}):worker=module('operator_worker')

class OperatorQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.inbox=self.root/'inbox';self.inbox.mkdir();self.results=self.root/'results';self.results.mkdir()
        self.config={'admin_id':pilot.UID,'fleet_profile':ct.PROFILE}
        patches=[patch.object(client,'INBOX',self.inbox),patch.object(client,'RESULTS',self.results),patch.object(worker,'INBOX',self.inbox),patch.object(worker,'RESULTS',self.results),patch.object(worker,'load_config',return_value=self.config),patch.object(worker.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=os.getuid()))]
        for p in patches:p.start();self.addCleanup(p.stop)
    def test_queue_backup_result_and_single_use_receipt(self):
        job=client.request('backup',pilot.UID)
        self.assertEqual((self.inbox/'request.json').stat().st_mode&0o777,0o600)
        body=(self.inbox/'request.json').read_bytes()
        with patch.object(worker,'execute',return_value='created') as execute:
            worker.consume();self.assertEqual(client.result(job)['state'],'done')
            (self.inbox/'request.json').write_bytes(body);worker.consume()
            execute.assert_called_once()
    def test_one_slot_never_overwrites_queued_request(self):
        first=client.request('backup',pilot.UID)
        with self.assertRaises(FileExistsError):client.request('backup',pilot.UID)
        self.assertEqual(json.loads((self.inbox/'request.json').read_text())['id'],first)
    def test_nonadmin_expired_unknown_fields_and_shell_actions_rejected(self):
        job=client.request('backup',pilot.UID);value=json.loads((self.inbox/'request.json').read_text())
        for changes in [{'uid':123},{'uid':True},{'created':int(time.time())-601},{'action':'reboot'},{'action':'backup;id'},{'command':'id'},{'id':'../../config'},{'code':'secret'}]:
            with self.assertRaises((ValueError,pilot.b.SafeError)):worker.validate({**value,**changes},self.config)
    def test_request_symlink_does_not_read_target(self):
        outside=self.root/'private';outside.write_text('secret')
        (self.inbox/'request.json').symlink_to(outside)
        with patch.object(worker,'execute') as execute:
            with self.assertRaises(OSError):worker.consume()
            execute.assert_not_called()
        self.assertEqual(outside.read_text(),'secret')
    def test_backup_rate_limit_is_enforced_by_root_worker(self):
        with patch.object(worker,'execute',return_value='ok') as execute:
            client.request('backup',pilot.UID);worker.consume()
            job=client.request('backup',pilot.UID);worker.consume()
            self.assertEqual(client.result(job)['state'],'failed');execute.assert_called_once()
    def test_enroll_validates_code_name_and_uses_same_transaction_engine(self):
        with patch.dict(sys.modules,{'connect':ct.c}):job=client.request('enroll',pilot.UID,ct.CODE,'HOME')
        value=worker.validate(json.loads((self.inbox/'request.json').read_text()),self.config)
        with patch.object(worker.connect,'lock',return_value=contextlib.nullcontext()),patch.object(worker.connect,'complete') as complete,patch.object(worker.backup,'create',return_value='/archive.gpg'):
            worker.execute(value,self.config)
            complete.assert_called_once_with(self.config,ct.CODE,ct.PROFILE,'HOME')
        for name in ['', 'bad\nname', 'x'*81]:self.assertFalse(client.valid_name(name))

class OperatorUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config={'admin_id':pilot.UID,'ssh_key':'/key','known_hosts':'/known','fleet_profile':ct.PROFILE,'routers':{'lab':{'host':'100.124.249.61','port':22,'name':'LAB'}}}
        self.store=pilot.b.Store(Path(self.temp.name)/'db');self.tg=pilot.TelegramFake()
        self.bot=pilot.b.Bot(self.config,self.tg,self.store,pilot.BridgeFake());self.addCleanup(self.bot.pool.shutdown)
    def texts(self):return [v['text'] for m,v in self.tg.calls if m=='sendMessage']
    def test_hwid_replaces_sequence_and_is_not_used_as_unique_access_key(self):
        self.store.cache_hwid('lab','abcd-1234-5678-90ef')
        self.assertEqual(self.bot.router_label('lab'),'LAB · HWID abcd-1234-5678-90ef')
        self.assertEqual(self.store.router_code('lab'),'R-000001')
        self.store.cache_hwid('lab',None);self.assertNotIn('R-000001',self.bot.router_label('lab'))
    def test_operator_menu_only_for_admin(self):
        self.store.change_access(pilot.UID,123,'lab',True)
        with self.assertRaises(pilot.b.SafeError):self.bot.operator_menu(123,'lab')
        self.bot.menu(123)
        self.assertNotIn('Администрирование бота',str(self.tg.calls))
        self.bot.menu(pilot.UID);self.assertIn('Администрирование бота',str(self.tg.calls))
    def test_client_cannot_submit_operator_callback_even_with_valid_button(self):
        self.store.change_access(pilot.UID,123,'lab',True)
        epoch=self.store.grant_epoch(123,'lab')
        token=self.store.button(123,'lab','operator_backup',grant_epoch=epoch)
        update={'update_id':800,'callback_query':{'id':'callback','from':{'id':123},'data':token,'message':{'chat':{'id':123,'type':'private'}}}}
        with patch.dict(sys.modules,{'operator_client':client}),patch.object(client,'request') as request:
            self.bot.handle(update);request.assert_not_called()
        self.assertEqual(self.store.operator_pending(),[])
    def test_status_caches_actual_hwid_without_rekeying_router_grants(self):
        self.store.change_access(pilot.UID,123,'lab',True)
        original=self.bot.bridge.call
        def call(router,command):
            value=original(router,command)
            if command=='xtlsbot-v1 status':value['hwid']='abcd-1234-5678-90ef'
            return value
        with patch.object(self.bot.bridge,'call',side_effect=call):self.bot.status(pilot.UID,'lab')
        self.assertIn('HWID abcd-1234-5678-90ef',self.texts()[-1])
        self.assertEqual(self.store.clients('lab'),[123])
    def test_name_command_code_flow_and_pending_double_click(self):
        with patch.dict(sys.modules,{'operator_client':client,'connect':ct.c}):
            self.bot.operator_input(pilot.UID,'HOME',{'stage':'name'})
            self.assertEqual(self.store.operator_dialog(pilot.UID)['stage'],'code')
            self.assertIn('clear\n(',self.texts()[-1])
            with patch.object(client,'request',return_value=ft.TX if hasattr(ft,'TX') else 'job') as request:
                self.bot.operator_input(pilot.UID,ct.CODE,self.store.operator_dialog(pilot.UID))
                self.assertIsNone(self.store.operator_dialog(pilot.UID))
                with self.assertRaises(pilot.b.SafeError):self.bot.operator_submit(pilot.UID,'backup')
                request.assert_called_once()
    def test_pending_result_survives_bot_restart_without_replay(self):
        job=self.store.operator_start(pilot.UID,'backup')
        restarted=pilot.b.Store(self.store.path)
        self.assertEqual(restarted.operator_pending()[0]['id'],job)
        with patch.dict(sys.modules,{'operator_client':client}),patch.object(client,'result',return_value={'id':job,'state':'done','text':'archive ready'}):
            self.bot.deliver_operator_results();self.bot.deliver_operator_results()
        self.assertEqual(self.texts().count('archive ready'),1)
    def test_request_failure_is_not_left_busy(self):
        with patch.dict(sys.modules,{'operator_client':client}),patch.object(client,'request',side_effect=OSError()):
            with self.assertRaises(pilot.b.SafeError):self.bot.operator_submit(pilot.UID,'backup')
        self.assertEqual(self.store.operator_pending(),[])
