import json,unittest
from test_native_catalogue import CatalogueTests
class Preserve(CatalogueTests):
 def test_sync_retains_user_rules_and_logging_and_authorization(self):
  previous=json.loads((self.d/'previous.json').read_text())
  previous['general'].update(fx_dashboard='1',fx_mode='auto',fx_start_authorized='0',fx_access_log='0',fx_rule_proxy_domains=['domain:example.com'],fx_rule_direct_ips=['203.0.113.0/24'],fx_rule_block_domains=['full:blocked.example'])
  (self.d/'previous.json').write_text(json.dumps(previous))
  prepared=self.prepare();g=prepared['general']
  for key in ['fx_start_authorized','fx_access_log','fx_rule_proxy_domains','fx_rule_direct_ips','fx_rule_block_domains']:
   self.assertEqual(g[key],previous['general'][key])
  c=self.generate();self.assertEqual(c['log']['access'],'none');self.assertEqual(c['log']['loglevel'],'warning')
  self.assertTrue(any(r.get('domain')==['domain:example.com'] for r in c['routing']['rules']))
if __name__=='__main__':unittest.main()
