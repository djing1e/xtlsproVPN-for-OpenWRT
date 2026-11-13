import copy,json,os,shutil,subprocess,time,unittest
from pathlib import Path
LIB=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files/usr/share/xray/lab'

@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class AutoSelection(unittest.TestCase):
    def run_uc(self,body):
        return json.loads(subprocess.check_output(['ucode','-e',"import {auto_decide,health_due} from '"+str(LIB/'auto_policy.mjs')+"';import {auto_run} from '"+str(LIB/'auto_runtime.mjs')+"';"+body],text=True))
    def sample(self,**patch):
        data=dict(enabled=True,now=1000,pid=42,active='cfgaaaaaa',health={'checked':100,'proxy_ok':True},nodes=[
            dict(id='cfgaaaaaa',alive=True,rtt_ms=200,checked=100,source='observatory',selected=True,probe_port=11500),
            dict(id='cfgbbbbbb',alive=True,rtt_ms=100,checked=100,source='observatory',selected=False,probe_port=11501)])
        data.update(patch);return data
    def policy(self,state=None,**patch):
        return self.run_uc('printf("%J",auto_decide('+json.dumps(state or {})+','+json.dumps(self.sample(**patch))+'));')
    def stable(self):return dict(pid=42,current='cfgaaaaaa',last_switch=0,pinned=True)
    def test_first_sample_pins_existing_selection(self):
        r=self.policy();self.assertEqual((r['action'],r['target']),('pin','cfgaaaaaa'))
    def test_cold_monitor_counts_the_first_failed_health_sample(self):
        r=self.policy(health={'checked':100,'proxy_ok':False});self.assertEqual(r['action'],'pin')
        state=r['state'];state['pinned']=True
        r=self.policy(state,health={'checked':101,'proxy_ok':False});self.assertEqual(r['action'],'failover')
    def test_three_distinct_measurements_and_five_minutes_required(self):
        state=self.stable();state['last_switch']=900
        for stamp in (100,160,220):
            data=self.sample();data['nodes'][0]['checked']=stamp;data['nodes'][1]['checked']=stamp
            r=self.policy(state,health={'checked':stamp,'proxy_ok':True},nodes=data['nodes']);state=r['state'];self.assertIsNone(r['action'])
        r=self.policy(state,now=1200,health={'checked':230,'proxy_ok':True},nodes=data['nodes']);self.assertEqual(r['action'],'optimize')
    def test_cached_observations_cannot_count_as_three_measurements(self):
        state=self.stable()
        for checked in range(1,10):
            r=self.policy(state,health={'checked':checked,'proxy_ok':True});state=r['state'];self.assertIsNone(r['action'])
        self.assertEqual(state['streak'],1)
    def test_asynchronous_observations_require_new_samples_from_both_nodes(self):
        state=self.stable()
        for checked,(current,candidate) in enumerate([(100,160),(160,160),(220,220),(220,280)],1):
            data=self.sample();data['nodes'][0]['checked']=current;data['nodes'][1]['checked']=candidate
            r=self.policy(state,health={'checked':checked,'proxy_ok':True},nodes=data['nodes']);state=r['state'];self.assertIsNone(r['action'])
        self.assertEqual(state['streak'],2)
    def test_both_latency_thresholds_required(self):
        for latency in (151,170):
            data=self.sample();data['nodes'][1]['rtt_ms']=latency
            r=self.policy(self.stable(),nodes=data['nodes']);self.assertIsNone(r['action']);self.assertEqual(r['state']['streak'],0)
    def test_two_failures_ignore_switch_cooldown_and_observatory_interval(self):
        state=self.stable();state['last_switch']=999
        for checked in (100,101):
            r=self.policy(state,health={'checked':checked,'proxy_ok':False});state=r['state']
        self.assertEqual(r['action'],'failover');self.assertEqual(r['candidates'][0]['id'],'cfgbbbbbb')
    def test_cached_failure_does_not_confirm_outage(self):
        r=self.policy(self.stable(),health={'checked':100,'proxy_ok':False})
        again=self.policy(r['state'],health={'checked':100,'proxy_ok':False});self.assertIsNone(again['action']);self.assertEqual(again['state']['failures'],1)
    def test_health_timer_ignores_background_interval_and_resets_on_pid(self):
        r=self.run_uc('printf("%J",[health_due({probe_at:100,probe_pid:42},109,42,10),health_due({probe_at:100,probe_pid:42},110,42,10),health_due({probe_at:100,probe_pid:42},101,43,60)]);')
        self.assertEqual(r,[False,True,True])
    def runtime(self,scenario='ok',mode='auto',stale=False):
        data=self.sample();data.update(autostart=True,enabled=True,interface={'up':True},core={'running':True,'pid':42},job={'state':'idle'})
        data['health']={'checked':int(time.time())-(100 if stale else 0),'proxy_pid':42,'proxy_ok':False}
        state=self.stable();state['failures']=1
        # Inject only the side-effect boundary; use the actual runtime transaction.
        return self.run_uc('''let calls=[],probes=[],overrides={fx_main:'fx_node:cfgaaaaaa',fx_auto_pool:''},failed=false;
            let deps={probe:port=>{push(probes,port);return {alive:'''+('false' if scenario=='dead' else 'port!=11499' if scenario=='active-failed' else 'true')+'''};},api:(op,args)=>{
                push(calls,[op,...args]);let tag=op=='bi'?args[1]:args[1];
                if(op=='bi')return {balancer:{override:{target:overrides[tag]}}};
                overrides[tag]=args[2]=='-r'?'':args[2];
                if('''+json.dumps(scenario)+'''=='timeout' && !failed){failed=true;die('timeout after mutation');}
                return {};
            }};
            let result=auto_run('''+json.dumps(data)+','+json.dumps({'fx_mode':mode,'fx_watchdog_enabled':'1'})+','+json.dumps(state)+''',1000,deps);
            printf('%J',{result,calls,probes,overrides});''')
    def test_replacement_verified_and_both_balancers_pinned(self):
        r=self.runtime();self.assertTrue(r['result']['changed']);self.assertEqual(r['probes'],[11501,11499]);self.assertTrue(all(x=='fx_node:cfgbbbbbb' for x in r['overrides'].values()))
    def test_uncertain_api_is_rolled_back(self):
        r=self.runtime('timeout');self.assertEqual(r['overrides'],{'fx_main':'fx_node:cfgaaaaaa','fx_auto_pool':''});self.assertEqual(r['result']['state']['reason'],'api_failed');self.assertTrue(r['result']['changed'])
    def test_failed_candidates_do_not_change_route(self):
        r=self.runtime('dead');self.assertFalse(r['calls']);self.assertFalse(r['result']['changed']);self.assertEqual(r['result']['state']['reason'],'no_candidate')
    def test_failed_active_route_after_api_switch_rolls_back(self):
        r=self.runtime('active-failed');self.assertEqual(r['overrides'],{'fx_main':'fx_node:cfgaaaaaa','fx_auto_pool':''});self.assertEqual(r['result']['state']['reason'],'api_failed')
    def test_missing_selection_metadata_does_not_move_healthy_traffic(self):
        r=self.policy(self.stable(),active=None);self.assertIsNone(r['action']);self.assertEqual(r['reason'],'selection_unknown')
    def test_manual_mode_and_stale_health_cannot_change_selection(self):
        for kwargs in ({'mode':'manual'},{'stale':True}):
            r=self.runtime(**kwargs);self.assertFalse(r['calls']);self.assertFalse(r['probes'])

if __name__=='__main__':unittest.main()
