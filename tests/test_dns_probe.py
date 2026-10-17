import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'package/xtlsprovpn/files/usr/share/xray/lab/dns_probe.mjs'
NOW = 1792239400


@unittest.skipUnless(shutil.which('ucode'), 'ucode runtime required')
class DNSProbe(unittest.TestCase):
    def setUp(self):
        self.options = {'enabled':'1','protocol':'doh','via_proxy':'1'}
        self.candidate = {
            'inbounds': [
                {'tag':'dns_server_inbound:5300','port':5300,'protocol':'dokodemo-door',
                 'settings':{'address':'1.1.1.1','port':53,'network':'tcp,udp'}},
                {'tag':'socks_inbound','port':1080}, {'tag':'api','port':8080}],
            'outbounds': [
                {'tag':'fx_node:a','protocol':'vless','settings':{'vnext':[{'address':'a.test'}]}},
                {'tag':'fx_node:b','protocol':'vless','settings':{'vnext':[{'address':'b.test'}]}},
                {'tag':'direct','protocol':'freedom','streamSettings':{'sockopt':{'mark':253}}},
                {'tag':'dns_server_outbound','protocol':'dns'},
                {'tag':'blackhole_outbound','protocol':'blackhole'}],
            'routing':{'domainStrategy':'IPIfNonMatch','balancers':[
                {'tag':'fx_main','selector':['fx_node:a','fx_node:b'],'strategy':{'type':'leastPing'}}],
                'rules':[
                    {'type':'field','inboundTag':['fx_dns_bootstrap'],'outboundTag':'direct'},
                    {'type':'field','inboundTag':['fx_dns_main:0'],'balancerTag':'fx_main'},
                    {'type':'field','inboundTag':['dns_server_inbound:5300','dns_server_inbound:5301'],
                     'outboundTag':'dns_server_outbound'},
                    {'type':'field','inboundTag':['socks_inbound'],'domain':['ext:large.dat:all'],
                     'balancerTag':'fx_main'},
                    {'type':'field','inboundTag':['api'],'outboundTag':'api'}]},
            'dns':{'tag':'dns_conf_inbound','servers':[
                {'address':'77.88.8.1','tag':'fx_dns_bootstrap'},
                {'address':'https://cloudflare-dns.com/dns-query','tag':'fx_dns_main:0'}]},
            'observatory':{'subjectSelector':['fx_node:'],'probeInterval':'60s'},
            'api':{},'metrics':{},'stats':{},'policy':{'system':{'statsInboundUplink':True}}}
        self.live = copy.deepcopy(self.candidate)
        for n, node in enumerate(('a','b')):
            tag = 'fx_probe:'+node
            self.live['inbounds'].append({'tag':tag,'listen':'127.0.0.1','port':11500+n,
                                         'protocol':'socks','settings':{'auth':'noauth','udp':False}})
            self.live['routing']['rules'].insert(0,{'inboundTag':[tag],'outboundTag':'fx_node:'+node})
        self.metrics = {'observatory':{
            'fx_node:a':{'alive':True,'delay':300,'last_try_time':NOW-10},
            'fx_node:b':{'alive':True,'delay':100,'last_try_time':NOW-10}}}

    def probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'input.json').write_text(json.dumps([self.candidate,self.options,self.live,self.metrics,NOW]))
            (p/'runner.uc').write_text(
                "import { dns_probe } from '"+str(MODULE)+"';\n"
                "let fs=require('fs'),p=json(fs.readfile(ARGV[0]));\n"
                "printf('%J',dns_probe(p[0],p[1],p[2],p[3],p[4]));\n")
            result=subprocess.run(['ucode',str(p/'runner.uc'),str(p/'input.json')],
                                  capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)

    def port(self, plan):
        return next(o for o in plan['config']['outbounds'] if o['protocol']=='socks')['settings']['servers'][0]['port']

    def test_doh_uses_healthy_dedicated_live_node_not_generic_socks(self):
        p=self.probe();c=p['config']
        self.assertEqual(p['mode'],'shared-transport')
        self.assertEqual(self.port(p),11501)
        self.assertEqual(c['dns'],self.candidate['dns'])
        self.assertEqual(c['inbounds'][0]['port'],15354)
        self.assertEqual(c['inbounds'][0]['listen'],'127.0.0.1')
        self.assertEqual(len(c['inbounds']),1)
        self.assertEqual(c['outbounds'][0]['protocol'],'blackhole')
        self.assertFalse(any(o['protocol']=='vless' for o in c['outbounds']))
        self.assertNotIn('balancers',c['routing'])
        self.assertFalse(any('balancerTag' in r for r in c['routing']['rules']))
        self.assertNotIn('ext:large.dat',json.dumps(c))
        self.assertTrue(all(key not in c for key in ('api','metrics','stats','policy','observatory')))
        self.assertEqual(c['routing']['rules'][0]['outboundTag'],'direct')
        self.assertEqual(c['routing']['rules'][1]['outboundTag'],'fx_dns_probe_proxy')
        self.assertEqual(p['minimum_kb'],32768)
        self.assertEqual(p['gomemlimit'],'24MiB')

    def test_manual_choice_is_preserved_even_when_another_node_is_faster(self):
        b=self.candidate['routing']['balancers'][0]
        b.update(selector=['fx_node:a'],strategy={'type':'random'})
        self.metrics=None
        self.assertEqual(self.port(self.probe()),11500)

    def test_udp_via_proxy_requires_independent_transport(self):
        self.options['protocol']='udp'
        p=self.probe()
        self.assertEqual(p['mode'],'independent')
        self.assertEqual(p['minimum_kb'],65536)
        self.assertIn('observatory',p['config'])
        self.assertTrue(any(o['protocol']=='vless' for o in p['config']['outbounds']))

    def test_direct_dns_needs_neither_live_core_nor_observations(self):
        self.options.update(protocol='udp',via_proxy='0')
        self.candidate['routing']['rules'][1]={'inboundTag':['fx_dns_main:0'],'outboundTag':'direct'}
        self.live=None;self.metrics=None
        p=self.probe()
        self.assertEqual(p['mode'],'shared-transport')
        self.assertFalse(any(o['protocol'] in ('vless','socks') for o in p['config']['outbounds']))

    def test_missing_live_core_retains_full_check(self):
        self.live=None
        self.assertEqual(self.probe()['mode'],'independent')

    def test_changed_transport_cannot_borrow_old_node(self):
        for o in self.candidate['outbounds']:
            if o['protocol']=='vless':o['streamSettings']={'sockopt':{'interface':'wan'}}
        self.assertEqual(self.probe()['mode'],'independent')

    def test_stale_or_failed_observations_cannot_select_auto_node(self):
        for o in self.metrics['observatory'].values():o['last_try_time']=NOW-181
        self.assertEqual(self.probe()['mode'],'independent')
        for o in self.metrics['observatory'].values():o.update(last_try_time=NOW,alive=False)
        self.assertEqual(self.probe()['mode'],'independent')

    def test_only_loopback_noauth_correctly_routed_listeners_are_trusted(self):
        original=copy.deepcopy(self.live)
        for change in ({'listen':'0.0.0.0'},{'port':1080.5},{'protocol':'http'},
                       {'settings':{'auth':'password'}}):
            self.live=copy.deepcopy(original)
            for inbound in self.live['inbounds']:
                if inbound['tag'].startswith('fx_probe:'):inbound.update(change)
            with self.subTest(change=change):self.assertEqual(self.probe()['mode'],'independent')
        self.live=copy.deepcopy(original)
        self.live['routing']['rules']=[r for r in self.live['routing']['rules']
                                      if not r.get('inboundTag',[''])[0].startswith('fx_probe:')]
        self.assertEqual(self.probe()['mode'],'independent')

    def test_dot_tls_wrapper_and_loopback_routing_survive(self):
        self.options['protocol']='dot'
        self.candidate['outbounds'] += [
            {'tag':'fx_dns_tls:0','protocol':'freedom','streamSettings':{'security':'tls'}},
            {'tag':'fx_dns_tls_dialer:0','protocol':'loopback','settings':{'inboundTag':'fx_dns_tls_inner:0'}}]
        self.candidate['routing']['rules'][1]={'inboundTag':['fx_dns_main:0'],'outboundTag':'fx_dns_tls:0'}
        self.candidate['routing']['rules'].insert(2,{'inboundTag':['fx_dns_tls_inner:0'],'balancerTag':'fx_main'})
        p=self.probe()
        self.assertEqual(p['mode'],'shared-transport')
        self.assertEqual(p['config']['routing']['rules'][2]['outboundTag'],'fx_dns_probe_proxy')
        self.assertTrue(any(o['protocol']=='loopback' for o in p['config']['outbounds']))

    def test_unsupported_balancer_falls_back_without_partial_rule_changes(self):
        self.candidate['routing']['rules'][1]['balancerTag']='other'
        p=self.probe()
        self.assertEqual(p['mode'],'independent')
        self.assertEqual(p['config']['routing']['rules'][1]['balancerTag'],'other')

    def test_disabled_custom_dns_keeps_original_profile_check(self):
        self.options['enabled']='0'
        self.assertEqual(self.probe()['mode'],'independent')

    def test_real_controller_writes_plan_and_private_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'uci.uc').write_text('export function cursor() { return {}; };')
            for name,data in [('candidate',self.candidate),('options',self.options),
                              ('live',self.live),('metrics',self.metrics)]:
                # The controller uses current time rather than the unit fixture clock.
                if name=='metrics':
                    import time
                    data=copy.deepcopy(data)
                    for item in data['observatory'].values():item['last_try_time']=int(time.time())
                (p/name).write_text(json.dumps(data))
            controller=MODULE.with_name('dns_control.uc')
            result=subprocess.run(['ucode','-L',str(p),str(controller),'probe-config',
                str(p/'candidate'),str(p/'probe'),str(p/'error'),str(p/'options'),
                str(p/'live'),str(p/'metrics'),str(p/'plan')],
                capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads((p/'plan').read_text())['mode'],'shared-transport')
            self.assertEqual((p/'probe').stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads((p/'probe').read_text())['log']['error'],str(p/'error'))


if __name__=='__main__':unittest.main()
