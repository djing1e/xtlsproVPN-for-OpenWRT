import json
import time
import threading
from pathlib import Path
from unittest.mock import patch
import unittest
import test_telegram as pilot

b,UID=pilot.b,pilot.UID
TARGET='1.4.8-r1'
DIGEST='a'*64

class FleetUpdates(unittest.TestCase):
    callback=pilot.TelegramTests.callback
    messages=pilot.TelegramTests.messages
    def setUp(self):
        pilot.TelegramTests.setUp(self)
        self.config['routers']={rid:{'name':rid,'host':'100.64.0.'+str(n+1),'port':22,'rescue':{'host':'127.0.0.1','port':23000+n}} for n,rid in enumerate(('lab','other','third'))}
        self.bot.locks={rid:threading.Lock() for rid in self.config['routers']}
        self.versions={rid:'1.4.7-r1' for rid in self.config['routers']}
        self.jobs={};self.calls=[];self.flags={};self.plans={}
        self.bot.latest_app_release=lambda **kwargs:(TARGET,DIGEST)
        self.bot.prepare_rescue=lambda uid,rid,quiet=False:{'netbird_connected':True}
        def call(uid,rid,cmd,epoch=None,transport=None):
            self.calls.append((rid,cmd,transport));flag=self.flags.get(rid,'')
            if cmd=='xtlsbot-v1 status':
                if flag=='offline':raise b.SafeError('No connection')
                return {'version':self.versions[rid],'running':flag!='stopped','enabled':flag!='stopped',
                        'proxy_ok':flag!='unhealthy','health_checked':int(time.time()),'operation_busy':flag=='busy','job':{}}
            if cmd=='xtlsbot-v1 admin-status':return {'netbird_connected':flag!='post-fail'}
            if cmd.startswith('xtlsbot-v1 update-check app '):
                request=cmd.split()[-1];self.jobs[rid]={'id':request,'component':'app','action':'check','state':'done'}
                self.plans[rid]={'id':request,'component':'app','available':'1.4.9-r1' if flag=='changed' else TARGET,'valid':True,'update_available':True}
                if flag=='cancel-check':self.store.fleet_cancel(UID,self.batch)
                return {'accepted':True,'id':request,'component':'app','action':'check'}
            if cmd.startswith('xtlsbot-v1 update-install app '):
                request=cmd.split()[-2];self.jobs[rid]={'id':request,'component':'app','action':'install','state':'failed' if flag=='install-fail' else 'done'}
                if flag!='install-fail':self.versions[rid]=TARGET
                if flag=='cancel-install':self.store.fleet_cancel(UID,self.batch)
                if flag=='lost-receipt':raise b.SafeError('Receipt lost')
                return {'accepted':True,'id':request,'component':'app','action':'install'}
            if cmd=='xtlsbot-v1 updates':return {'job':dict(self.jobs[rid]),'plans':[dict(self.plans.get(rid,{}))]}
            raise AssertionError(cmd)
        self.bot.router_call=call
    def tearDown(self):pilot.TelegramTests.tearDown(self)
    def create(self,routers=None):
        self.batch=self.store.fleet_create(UID,TARGET,DIGEST,[(rid,self.bot.fleet_identity(self.config['routers'][rid])) for rid in (routers or self.config['routers'])])
        return self.batch
    def run_batch(self,resume=False):
        self.store.fleet_start(UID,self.batch,resume)
        with patch.object(b.time,'sleep'):self.bot.fleet_worker(UID,'lab',self.batch,resume)
        return self.store.fleet_get(UID,self.batch)
    def installs(self):return [c for c in self.calls if 'update-install' in c[1]]
    def test_all_routers_updated_one_at_a_time_and_verified(self):
        self.create();data=self.run_batch()
        self.assertEqual(data['state'],'done');self.assertEqual([i['state'] for i in data['items']],['updated']*3)
        self.assertEqual(len(self.installs()),3)
        self.assertTrue(all(c[2]=='rescue' for c in self.installs()))
        for rid in self.config['routers']:
            self.assertIn((rid,'xtlsbot-v1 status','netbird'),self.calls)
            self.assertIn((rid,'xtlsbot-v1 admin-status','rescue'),self.calls)
        self.assertIn('обновлено: 3',self.messages()[-1])
    def test_current_offline_and_stopped_are_counted_without_install(self):
        self.versions['lab']=TARGET;self.flags.update(other='offline',third='stopped')
        self.create();data=self.run_batch()
        self.assertEqual([i['state'] for i in data['items']],['current','offline','skipped']);self.assertFalse(self.installs())
        self.assertIn('уже актуально: 1',self.messages()[-1]);self.assertIn('Недоступны: 1',self.messages()[-1])
    def test_newer_version_never_downgraded(self):
        self.versions['lab']='1.5.0-r1';self.create(['lab']);self.assertEqual(self.run_batch()['items'][0]['state'],'current');self.assertFalse(self.installs())
    def test_failed_canary_stops_remaining_routers(self):
        self.flags['lab']='install-fail';self.create();data=self.run_batch()
        self.assertEqual(data['state'],'paused');self.assertEqual([i['state'] for i in data['items']],['failed','queued','queued'])
        self.assertEqual(len(self.installs()),1)
    def test_lost_receipt_is_reconciled_without_resending_install(self):
        self.flags['lab']='lost-receipt';self.create();data=self.run_batch()
        self.assertEqual(data['state'],'paused');self.assertEqual(data['items'][0]['state'],'unconfirmed')
        self.flags['lab']='';data=self.run_batch(resume=True)
        self.assertEqual(data['state'],'done');self.assertEqual(len(self.installs()),3)
        self.assertEqual(sum(rid=='lab' for rid,_,_ in self.installs()),1)
    def test_post_install_failure_pauses_and_resumes_only_after_reconciliation(self):
        self.flags['lab']='post-fail';self.create();data=self.run_batch()
        self.assertEqual(data['items'][0]['state'],'unconfirmed');self.assertEqual(len(self.installs()),1)
        data=self.run_batch(resume=True);self.assertEqual(data['state'],'paused');self.assertEqual(len(self.installs()),1)
        self.flags['lab']='';self.assertEqual(self.run_batch(resume=True)['state'],'done');self.assertEqual(len(self.installs()),3)
    def test_cancel_during_check_never_dispatches_install(self):
        self.flags['lab']='cancel-check';self.create();data=self.run_batch()
        self.assertEqual(data['state'],'done');self.assertEqual([i['state'] for i in data['items']],['cancelled']*3);self.assertFalse(self.installs())
    def test_cancel_finishes_current_install_and_cancels_rest(self):
        self.flags['lab']='cancel-install';self.create();data=self.run_batch()
        self.assertEqual(data['state'],'done');self.assertEqual([i['state'] for i in data['items']],['updated','cancelled','cancelled']);self.assertEqual(len(self.installs()),1)
    def test_busy_lock_and_health_preflight_do_not_mutate(self):
        self.bot.locks['lab'].acquire();self.addCleanup(self.bot.locks['lab'].release)
        self.flags.update(other='busy',third='unhealthy');self.create();data=self.run_batch()
        self.assertEqual([i['state'] for i in data['items']],['skipped']*3);self.assertFalse(self.installs())
    def test_changed_router_identity_is_not_updated(self):
        self.create(['lab']);self.config['routers']['lab']['host']='100.64.99.1'
        data=self.run_batch();self.assertEqual(data['items'][0]['reason'],'identity');self.assertFalse(self.calls)
    def test_changed_release_pauses_without_install(self):
        self.flags['lab']='changed';self.create();data=self.run_batch()
        self.assertEqual(data['state'],'paused');self.assertEqual(data['items'][0]['reason'],'release_changed');self.assertFalse(self.installs())
    def test_same_version_different_digest_is_not_installed(self):
        self.create();self.bot.latest_app_release=lambda **kwargs:(TARGET,'b'*64)
        self.assertEqual(self.run_batch()['state'],'paused');self.assertFalse(self.installs())
    def test_cooldown_shared_with_individual_admin_actions(self):
        self.store.begin_admin(999,UID,'lab','reboot');self.store.finish(999,'done')
        self.create(['lab']);data=self.run_batch();self.assertEqual(data['items'][0]['reason'],'cooldown');self.assertFalse(self.installs())
    def test_fresh_post_install_health_is_required(self):
        self.create(['lab']);original=self.bot.router_call
        def call(uid,rid,cmd,**kwargs):
            data=original(uid,rid,cmd,**kwargs)
            if cmd.endswith(' status') and self.versions[rid]==TARGET:data['health_checked']=int(time.time())-10
            return data
        self.bot.router_call=call
        self.assertEqual(self.run_batch()['items'][0]['state'],'unconfirmed')
    def test_restart_retains_install_intent_and_does_not_replay(self):
        self.create(['lab']);self.store.fleet_start(UID,self.batch)
        item=self.store.fleet_get(UID,self.batch)['items'][0];self.store.fleet_item(self.batch,'lab','checking')
        request='11111111-2222-4333-8444-555555555555'
        self.store.fleet_install_intent(UID,self.batch,item,request)
        self.versions['lab']=TARGET;self.jobs['lab']={'id':request,'component':'app','action':'install','state':'done'}
        self.store=b.Store(self.store.path);self.bot.store=self.store
        data=self.store.fleet_get(UID,self.batch)
        self.assertEqual(data['state'],'paused');self.assertEqual(data['items'][0]['state'],'unconfirmed')
        self.assertEqual(self.run_batch(resume=True)['items'][0]['state'],'updated');self.assertFalse(self.installs())
    def test_duplicate_start_or_second_active_batch_rejected(self):
        first=self.create();self.store.fleet_start(UID,first)
        with self.assertRaises(b.SafeError):self.store.fleet_start(UID,first)
        second=self.create()
        with self.assertRaises(b.SafeError):self.store.fleet_start(UID,second)
    def test_expired_confirmation_does_not_start(self):
        self.create()
        with patch.object(b.time,'time',return_value=time.time()+121):
            with self.assertRaises(b.SafeError):self.store.fleet_start(UID,self.batch)
        self.assertFalse(self.installs())
    def test_non_admin_callbacks_cannot_start_cancel_or_read_batch(self):
        self.create();client=123456;self.store.change_access(UID,client,'lab',True)
        for action,target in [('fleet_menu',''),('fleet_prepare',''),('fleet_confirm',self.batch),('fleet_resume',self.batch),('fleet_cancel',self.batch),('fleet_status',self.batch+':0')]:
            token=self.store.button(client,'lab',action,target,self.store.grant_epoch(client,'lab'))
            self.bot.handle(self.callback(token,uid=client))
        self.assertEqual(self.store.fleet_get(UID,self.batch)['state'],'draft');self.assertFalse(self.calls)
    def test_cancelled_preview_invalidates_its_old_confirmation(self):
        self.bot.fleet_prepare(UID,'lab')
        buttons=[button for _,payload in self.tg.calls for row in payload.get('reply_markup',{}).get('inline_keyboard',[]) for button in row]
        confirm=next(x['callback_data'] for x in buttons if x['text'].startswith('✅ Обновить'))
        cancel=next(x['callback_data'] for x in buttons if x['text']=='Отмена')
        with patch.object(self.bot.pool,'submit') as submit:
            self.bot.handle(self.callback(cancel));self.bot.handle(self.callback(confirm,update_id=43))
            submit.assert_not_called()
        self.assertEqual(self.store.fleet_get(UID)['state'],'done');self.assertFalse(self.calls)
    def test_confirmation_button_is_one_use_and_does_not_install_before_confirmation(self):
        self.bot.fleet_prepare(UID,'lab');self.assertFalse(self.calls)
        buttons=[row for _,payload in self.tg.calls for row in payload.get('reply_markup',{}).get('inline_keyboard',[])]
        token=next(button['callback_data'] for row in buttons for button in row if button['text'].startswith('✅ Обновить'))
        with patch.object(self.bot.pool,'submit') as submit:
            self.bot.handle(self.callback(token));self.bot.handle(self.callback(token,update_id=43));self.assertEqual(submit.call_count,1)
    def test_report_failure_does_not_repeat_or_abort_successful_installs(self):
        self.create();self.bot.send=lambda *a,**kw:(_ for _ in ()).throw(b.SafeError('Telegram unavailable'))
        data=self.run_batch();self.assertEqual(data['state'],'done');self.assertEqual(len(self.installs()),3)

class OfficialRelease(unittest.TestCase):
    def test_exact_official_manifest_and_asset_are_required(self):
        import copy
        url='https://github.com/djing1e/xtlsproVPN-for-OpenWRT/releases/download/v1.4.8/update.json'
        release={'tag_name':'v1.4.8','draft':False,'prerelease':False,'assets':[{'name':'update.json','browser_download_url':url},{'name':'xtlsprovpn-'+TARGET+'.apk','size':123,'digest':'sha256:'+DIGEST}]}
        manifest={'schema':1,'tag':'v1.4.8','version':TARGET,'apk':{'name':'xtlsprovpn-'+TARGET+'.apk','sha256':DIGEST,'size':123}}
        for case in ('ok','draft','evil-tag','digest','wrong-version','oversize'):
            r=copy.deepcopy(release);m=copy.deepcopy(manifest)
            if case=='draft':r['draft']=True
            if case=='evil-tag':r['tag_name']='../../evil'
            if case=='digest':r['assets'][1]['digest']='sha256:'+'b'*64
            if case=='wrong-version':m['version']='1.4.9-r1'
            if case=='oversize':m['apk']['size']=8388609
            class Response:
                def __init__(self,body):self.body=body
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def read(self,n):return json.dumps(self.body).encode()
            calls=[]
            class Opener:
                def open(self,request,timeout):
                    calls.append(request.full_url)
                    return Response(r if len(calls)==1 else m)
            with self.subTest(case=case),patch.object(b.urllib.request,'build_opener',return_value=Opener()):
                if case=='ok':self.assertEqual(b.Bot.latest_app_release(object.__new__(b.Bot)),(TARGET,DIGEST))
                else:
                    with self.assertRaises(b.SafeError):b.Bot.latest_app_release(object.__new__(b.Bot))
                self.assertTrue(all(u in (url,'https://api.github.com/repos/djing1e/xtlsproVPN-for-OpenWRT/releases/latest') for u in calls))


class FleetAdministrativeSafety(unittest.TestCase):
    setUp=FleetUpdates.setUp
    tearDown=FleetUpdates.tearDown
    create=FleetUpdates.create
    run_batch=FleetUpdates.run_batch
    installs=FleetUpdates.installs
    def test_server_operator_cannot_restart_bot_during_active_batch(self):
        self.create();self.store.fleet_start(UID,self.batch)
        with self.assertRaises(b.SafeError):self.store.operator_start(UID,'backup')
    def test_pending_server_operation_prevents_batch_start(self):
        self.store.operator_start(UID,'backup');self.create()
        with self.assertRaises(b.SafeError):self.store.fleet_start(UID,self.batch)
        self.assertFalse(self.calls)
    def test_disabled_rescue_never_installs(self):
        self.bot.prepare_rescue=lambda *a,**kw:(_ for _ in ()).throw(b.SafeError('No rescue'))
        self.create();data=self.run_batch();self.assertEqual(data['state'],'done');self.assertFalse(self.installs())
        self.assertEqual([i['reason'] for i in data['items']],['rescue']*3)
    def test_replaced_job_never_replays_install(self):
        self.flags['lab']='lost-receipt';self.create();self.run_batch()
        self.jobs['lab']['id']='22222222-2222-4333-8444-555555555555'
        self.assertEqual(self.run_batch(resume=True)['state'],'paused');self.assertEqual(len(self.installs()),1)
    def test_cancelled_batch_stays_cancelled_after_process_restart(self):
        self.create();self.store.fleet_start(UID,self.batch)
        self.store.fleet_item(self.batch,'lab','checking');self.store.fleet_cancel(UID,self.batch)
        self.store=b.Store(self.store.path);self.bot.store=self.store
        data=self.store.fleet_get(UID,self.batch)
        self.assertEqual(data['state'],'done');self.assertEqual([i['state'] for i in data['items']],['cancelled']*3)
    def test_native_running_job_does_not_allow_remaining_installations(self):
        self.flags['lab']='lost-receipt';self.create();self.run_batch();self.jobs['lab']['state']='running'
        self.assertEqual(self.run_batch(resume=True)['state'],'paused');self.assertEqual(len(self.installs()),1)
    def test_fleet_activity_is_visible_to_transactional_upgrader(self):
        import importlib.util
        source=Path(__file__).resolve().parents[1]/'server/upgrade.py'
        spec=importlib.util.spec_from_file_location('fleet_upgrade_test',source);upgrade=importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',{'bot':b}):spec.loader.exec_module(upgrade)
        self.create();self.assertEqual(upgrade.running_operations(self.store.path),0)
        self.store.fleet_start(UID,self.batch);self.assertEqual(upgrade.running_operations(self.store.path),1)

if __name__=='__main__':unittest.main()
