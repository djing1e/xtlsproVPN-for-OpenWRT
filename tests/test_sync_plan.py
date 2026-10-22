import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import test_dns_probe as fixtures

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/'package/xtlsprovpn/files/usr/share/xray/lab'

@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class SyncPlan(unittest.TestCase):
    def setUp(self):fixtures.DNSProbe.setUp(self)
    def plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'in.json').write_text(json.dumps([self.candidate,self.live,self.metrics,fixtures.NOW]))
            (p/'run.uc').write_text("import { sync_plan } from '"+str(LIB/'sync_plan.mjs')+"';\nlet a=json(require('fs').readfile(ARGV[0]));printf('%J',sync_plan(a[0],a[1],a[2],a[3]));")
            r=subprocess.run(['ucode',str(p/'run.uc'),str(p/'in.json')],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def node(self,c):return [o for o in c['outbounds'] if o['tag'].startswith('fx_node:')]
    def test_auto_checks_preferred_path_before_alternatives_without_client_rules(self):
        p=self.plan();self.assertEqual(p['mode'],'sequential');self.assertEqual(p['changed'],0)
        self.assertEqual([s['node'] for s in p['steps']],['fx_node:b','fx_node:a']);self.assertTrue(all(s['alternative'] for s in p['steps']));c=p['steps'][0]['config']
        self.assertEqual(self.node(c)[0]['tag'],'fx_node:b');self.assertEqual(len(self.node(c)),1)
        self.assertEqual(c['routing']['rules'][0]['outboundTag'],'fx_node:b')
        self.assertNotIn('ext:large.dat',json.dumps(c));self.assertEqual(c['dns'],self.candidate['dns'])
        for key in ['observatory','metrics','api','stats','policy','fakedns']:self.assertNotIn(key,c)
        self.assertEqual(c['outbounds'][0]['protocol'],'blackhole')
        self.assertEqual(p['minimum_kb'],32768);self.assertEqual(p['gomemlimit'],'24MiB')
    def test_changed_nodes_are_all_checked_before_selected_dns(self):
        self.candidate['outbounds'][0]['settings']['vnext'][0]['address']='changed.test'
        p=self.plan();self.assertEqual(p['changed'],1);self.assertEqual(len(p['steps']),3)
        self.assertEqual([s['port'] for s in p['steps']],[12000,11980,11980])
        self.assertFalse(p['steps'][0]['dns']);self.assertTrue(p['steps'][1]['dns'])
        self.assertEqual(p['steps'][0]['node'],'fx_node:a')
    def test_manual_selection_ignores_another_faster_node(self):
        self.candidate['routing']['balancers'][0].update(selector=['fx_node:a'],strategy={'type':'random'})
        p=self.plan();self.assertEqual(p['steps'][-1]['node'],'fx_node:a');self.assertFalse(p['steps'][-1]['alternative']);self.assertEqual(len(p['steps']),1)
    def test_missing_live_configuration_tests_every_node(self):
        self.live={};self.assertEqual(self.plan()['changed'],2)
    def test_json_key_order_does_not_mark_unchanged_transport_changed(self):
        self.live['outbounds'][0]=dict(reversed(list(self.live['outbounds'][0].items())))
        self.assertEqual(self.plan()['changed'],0)
    def test_candidate_transport_and_output_interface_are_preserved(self):
        o=self.candidate['outbounds'][0]
        o['streamSettings']={'network':'xhttp','security':'reality','sockopt':{'mark':253,'interface':'wan'}}
        self.assertEqual(self.node(self.plan()['steps'][0]['config'])[0],o)
    def test_dns_uses_candidate_node_while_bootstrap_stays_direct(self):
        c=self.plan()['steps'][0]['config'];rules=c['routing']['rules']
        self.assertEqual(next(r for r in rules if 'fx_dns_bootstrap' in r['inboundTag'])['outboundTag'],'direct')
        self.assertEqual(next(r for r in rules if 'fx_dns_main:0' in r['inboundTag'])['outboundTag'],'fx_node:b')
        self.assertFalse(any('balancerTag' in r for r in rules))
    def test_unsupported_dns_geo_or_transport_dependencies_use_full_guard(self):
        for mode in ['geo','chain','unknown-dns-target']:
            with self.subTest(mode=mode):
                original=copy.deepcopy(self.candidate)
                if mode=='geo':self.candidate['dns']['servers'][0]['domains']=['ext:database.dat:all']
                elif mode=='chain':self.candidate['outbounds'][1]['streamSettings']={'sockopt':{'dialerProxy':'missing'}}
                else:self.candidate['routing']['rules'][0]['outboundTag']='missing'
                self.assertIsNone(self.plan());self.candidate=original
    def test_controller_writes_sequential_plan_and_private_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            for path,data in [('candidate',self.candidate),('live',self.live),('metrics',self.metrics)]:
                (d/path).write_text(json.dumps(data))
            r=subprocess.run(['ucode',str(LIB/'sync_probe.uc'),str(d/'candidate'),str(d/'live'),str(d/'probe'),
                              str(d/'ports'),str(d/'error.log'),str(d/'metrics'),str(d/'plan')],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr);p=json.loads((d/'plan').read_text())
            self.assertEqual(p['mode'],'sequential')
            lines=(d/'ports').read_text().splitlines();self.assertEqual(len(lines),2)
            port,path,dns=lines[0].split();self.assertEqual(port,'11980');self.assertEqual(dns,'2')
            self.assertEqual(Path(path).suffix,'.json', 'Xray detects the config format from its extension')
            c=json.loads(Path(path).read_text());self.assertEqual(len(self.node(c)),1)
            self.assertEqual(Path(path).stat().st_mode & 0o777,0o600)
            self.assertEqual(c['log']['error'],str(d/'error.log'))

@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class OperationErrors(unittest.TestCase):
    def test_messages_explain_failures_without_disclosing_log_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);runner=d/'run.uc'
            runner.write_text("import { operation_error } from '"+str(LIB/'operation_error.mjs')+"';printf('%J',operation_error(ARGV[0],'generic failure'));")
            cases=[('Not enough RAM for isolated candidate testing; required_kb=32768; available_kb=31000;','32 МиБ'),
                   ('Not enough RAM for isolated candidate testing; live state retained.','RAM'),
                   ('Candidate HTTPS failed on local probe 12000.','HTTPS'),
                   ('Candidate DNS failed.','DNS')]
            for text,expected in cases:
                secret=' https://private.invalid/sub/PRIVATE-TOKEN'
                r=subprocess.run(['ucode',str(runner),text+secret],capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr);message=json.loads(r.stdout)
                self.assertIn(expected,message);self.assertNotIn('PRIVATE-TOKEN',message)

if __name__=='__main__':unittest.main()
