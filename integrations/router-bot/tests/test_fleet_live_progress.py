import json
import time
import unittest
from unittest.mock import patch
import test_fleet_updates as fixtures

b,UID,TARGET=fixtures.b,fixtures.UID,fixtures.TARGET

class FleetLiveProgress(unittest.TestCase):
    setUp=fixtures.FleetUpdates.setUp
    tearDown=fixtures.FleetUpdates.tearDown
    create=fixtures.FleetUpdates.create
    run_batch=fixtures.FleetUpdates.run_batch
    installs=fixtures.FleetUpdates.installs
    callback=fixtures.FleetUpdates.callback
    def data(self):return self.store.fleet_get(UID,self.batch)
    def tick(self,at=None):
        at=max(time.time(),self.data()['message_updated'])+4 if at is None else at
        with patch.object(b.time,'time',return_value=at):self.bot.fleet_progress_step()
    def edits(self):return [v for k,v in self.tg.calls if k=='editMessageText']
    def sends(self):return [v for k,v in self.tg.calls if k=='sendMessage']
    def text(self):return self.tg.live[self.data()['message_id']]['text']
    def test_plan_and_final_result_share_one_message(self):
        self.bot.fleet_prepare(UID,'lab');self.batch=self.store.fleet_get(UID)['id']
        number=self.data()['message_id'];self.run_batch()
        self.assertEqual(len(self.sends()),1);self.assertTrue(self.edits())
        self.assertTrue(all(v['message_id']==number for v in self.edits()))
        self.assertIn('Завершено',self.text());self.assertIn('100%',self.text());self.assertIn('обработано 3/3',self.text())
        self.assertEqual(len(self.installs()),3)
    def test_progress_counts_only_candidates_and_shows_current_phase(self):
        self.versions['third']=TARGET;self.bot.fleet_prepare(UID,'lab');self.batch=self.store.fleet_get(UID)['id']
        self.store.fleet_start(UID,self.batch);self.store.fleet_item(self.batch,'lab','checking');self.tick()
        self.assertIn('0%',self.text());self.assertIn('обработано 0/2',self.text());self.assertIn('Сейчас: lab · проверка каталога',self.text())
        self.store.fleet_item(self.batch,'lab','installing','verify');self.tick();self.assertIn('проверка результата',self.text())
        self.store.fleet_item(self.batch,'lab','updated');self.store.fleet_item(self.batch,'other','installing');self.tick()
        self.assertIn('50%',self.text());self.assertIn('обработано 1/2',self.text());self.assertIn('Сейчас: other · установка',self.text())
        self.assertEqual(len(self.sends()),1);self.assertFalse(self.installs())
    def test_manual_refresh_is_throttled_then_updates_buttons(self):
        self.create();self.bot.fleet_report(UID,'lab',self.batch);self.bot.fleet_report(UID,'lab',self.batch)
        self.assertFalse(self.edits());self.tick();self.assertEqual(len(self.edits()),1);self.assertEqual(len(self.sends()),1)
    def test_unchanged_automatic_report_does_not_edit(self):
        self.create();self.store.fleet_item(self.batch,'lab','queued');self.tick()
        self.assertFalse(self.edits());self.assertEqual(len(self.sends()),1)
    def test_rate_limit_delays_edits_without_creating_new_messages(self):
        self.create();base=self.data()['message_updated'];original=self.tg.call;attempts=[]
        def call(method,**payload):
            if method=='editMessageText':
                attempts.append(method)
                if len(attempts)==1:raise b.SafeError('Limited',429,retry_after=10)
            return original(method,**payload)
        self.tg.call=call;self.store.fleet_start(UID,self.batch);self.tick(base+4)
        self.assertEqual(len(attempts),1);self.tick(base+5);self.assertEqual(len(attempts),1)
        self.store.fleet_state(UID,self.batch,'paused');self.tick(base+15)
        self.assertEqual(len(attempts),2);self.assertIn('Приостановлено',self.text());self.assertEqual(len(self.sends()),1)
    def test_edit_timeout_never_falls_back_to_another_send(self):
        self.create();base=self.data()['message_updated'];original=self.tg.call;once=[True]
        def call(method,**payload):
            result=original(method,**payload)
            if method=='editMessageText' and once[0]:once[0]=False;raise b.SafeError('Timeout')
            return result
        self.tg.call=call;self.store.fleet_start(UID,self.batch);self.tick(base+4);self.tick(base+20)
        self.assertEqual(len(self.sends()),1);self.assertEqual(self.data()['message_id'],1)
    def test_uncertain_initial_send_requires_user_action_to_adopt_message(self):
        original=self.tg.call
        def call(method,**payload):
            result=original(method,**payload)
            if method=='sendMessage':raise b.SafeError('Lost receipt')
            return result
        self.tg.call=call;self.bot.fleet_prepare(UID,'lab');self.batch=self.store.fleet_get(UID)['id']
        self.assertIsNone(self.data()['message_id']);self.tick(time.time()+20);self.tick(time.time()+40)
        self.assertEqual(len(self.sends()),1)
        self.store.fleet_ui_adopt(UID,self.batch,1);self.tg.call=original;self.tick(time.time()+50)
        self.assertEqual(self.data()['message_id'],1);self.assertEqual(len(self.sends()),1)
    def test_deleted_message_is_not_recreated_by_background_refresh(self):
        self.create();number=self.data()['message_id'];del self.tg.live[number]
        self.store.fleet_start(UID,self.batch);self.tick()
        self.assertIsNone(self.data()['message_id']);self.tick(time.time()+30);self.assertEqual(len(self.sends()),1)
        with patch.object(b.time,'time',return_value=self.data()['message_retry_at']+1):self.bot.fleet_report(UID,'lab',self.batch)
        self.assertEqual(len(self.sends()),2);self.assertNotEqual(self.data()['message_id'],number)
    def test_not_modified_error_is_acknowledged_without_spam(self):
        self.create();self.store.fleet_start(UID,self.batch)
        def call(method,**payload):raise b.SafeError('Same',400,'not_modified')
        self.tg.call=call;self.tick();self.assertEqual(self.data()['message_dirty'],0);self.assertEqual(len(self.sends()),1)
    def test_process_restart_keeps_message_and_pauses_queue(self):
        self.create();number=self.data()['message_id'];self.store.fleet_start(UID,self.batch)
        self.store.fleet_item(self.batch,'lab','installing',request='11111111-2222-4333-8444-555555555555')
        self.store=b.Store(self.store.path);self.bot.store=self.store;self.tick()
        self.assertEqual(self.data()['message_id'],number);self.assertIn('Приостановлено',self.text())
        self.assertEqual(self.data()['items'][0]['state'],'unconfirmed');self.assertEqual(len(self.sends()),1);self.assertFalse(self.installs())
    def test_newer_state_is_not_lost_during_slow_message_edit(self):
        self.create();self.store.fleet_start(UID,self.batch);self.store.fleet_item(self.batch,'lab','updated')
        original=self.tg.call;once=[True]
        def call(method,**payload):
            if method=='editMessageText' and once[0]:once[0]=False;self.store.fleet_item(self.batch,'other','updated')
            return original(method,**payload)
        self.tg.call=call;self.tick();self.assertEqual(self.data()['message_dirty'],1)
        self.tick();self.assertEqual(self.data()['message_dirty'],0);self.assertIn('обновлено: 2',self.text())
    def test_pagination_remains_selected_during_background_updates(self):
        import threading
        for n in range(10):
            rid='r'+str(n);self.config['routers'][rid]={'name':rid,'host':'100.64.2.'+str(n+1),'port':22};self.bot.locks[rid]=threading.Lock();self.versions[rid]=TARGET
        self.create();self.store.fleet_start(UID,self.batch)
        at=self.data()['message_updated']+4
        with patch.object(b.time,'time',return_value=at):self.bot.fleet_report(UID,'lab',self.batch,1)
        self.assertEqual(self.data()['message_page'],1);self.store.fleet_item(self.batch,'lab','updated');self.tick()
        self.assertIn('• r7:',self.text());self.assertNotIn('• lab:',self.text());self.assertEqual(len(self.sends()),1)
    def test_resuming_legacy_batch_preserves_original_progress_total(self):
        self.create();self.store.fleet_item(self.batch,'lab','updated');self.store.fleet_item(self.batch,'third','current')
        with self.store.connect() as db:db.execute("UPDATE fleet_updates SET state='paused',progress_total=NULL WHERE id=?",(self.batch,))
        self.store.fleet_start(UID,self.batch,resume=True);self.tick()
        self.assertIn('обработано 1/2',self.text());self.assertIn('50%',self.text())
    def test_completed_cancelled_card_is_not_republished_on_every_restart(self):
        self.create();self.store.fleet_cancel(UID,self.batch);self.tick();before=len(self.edits())
        self.store=b.Store(self.store.path);self.bot.store=self.store
        self.tick(self.data()['message_updated']+400)
        self.assertEqual(len(self.edits()),before)
    def test_background_publisher_limits_output_across_batches(self):
        first=self.create();self.store.fleet_item(first,'lab','updated')
        second=self.create();self.store.fleet_item(second,'lab','updated')
        before=len(self.edits());self.tick()
        self.assertEqual(len(self.edits())-before,1)
        self.tick();self.assertEqual(len(self.edits())-before,2)
    def test_worker_completes_even_when_telegram_is_unavailable(self):
        self.create();before=len(self.tg.calls)
        self.tg.call=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('worker must not use Telegram'))
        self.store.fleet_start(UID,self.batch)
        with patch.object(b.time,'sleep'):self.bot.fleet_worker(UID,'lab',self.batch)
        self.assertEqual(len(self.tg.calls),before);self.assertEqual(self.data()['state'],'done');self.assertEqual(len(self.installs()),3)

class TelegramEditErrors(unittest.TestCase):
    def test_only_safe_error_tags_and_retry_delay_are_exposed(self):
        for description,tag in [('Bad Request: message is not modified','not_modified'),('Bad Request: message to edit not found','message_missing'),('secret token URL','')]:
            error=b.telegram_error({'description':description,'error_code':400,'parameters':{'retry_after':8}})
            self.assertEqual(error.api_reason,tag or None);self.assertEqual(error.retry_after,8)
            self.assertNotIn(description,str(error))
        self.assertIsNone(b.telegram_error({'parameters':'invalid'},429).retry_after)
    def test_http_error_body_preserves_edit_reason_without_leaking_token(self):
        import io
        error=b.urllib.error.HTTPError('https://api.telegram.org/botSECRET/method',400,'error',{},io.BytesIO(json.dumps({'error_code':400,'description':'Bad Request: message is not modified'}).encode()))
        telegram=b.Telegram('SECRET')
        with patch.object(telegram.opener,'open',side_effect=error):
            with self.assertRaises(b.SafeError) as caught:telegram.call('editMessageText')
        self.assertEqual(caught.exception.api_reason,'not_modified');self.assertEqual(caught.exception.code,400)
        self.assertNotIn('SECRET',str(caught.exception))

if __name__=='__main__':unittest.main()
