import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'package/xtlsprovpn/files'
MOCK = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
d=Path(os.environ['TEST_ROOT']); name=Path(sys.argv[0]).name; args=sys.argv[1:]
scenario=os.environ['TEST_SCENARIO']
with (d/'events').open('a') as f:f.write(name+' '+' '.join(args)+'\n')
if name=='init':
 if args[0]=='running':sys.exit(0 if scenario=='still-running' else 1)
 sys.exit(1 if scenario==args[0] else 0)
if name=='uci':sys.exit(1 if scenario=='uci' else 0)
if name in ('dnsmasq','firewall','policy','redirects'):sys.exit(1 if scenario in (name,'all') else 0)
if name=='ip':sys.exit(1) # already absent: cleanup must still reach firewall
if name=='nft':
 if args[:2]==['list','table']:sys.exit(0)
 if args[:2]==['list','chain']:sys.exit(0 if args[-1] in ('xray_prerouting','fx_dns_redirect') else 1)
 if args[:2]==['flush','chain']:
  assert args[2:4]==['inet','fw4']
  assert args[-1] in ('xray_prerouting','fx_dns_redirect')
  sys.exit(1 if scenario=='all' else 0)
 raise RuntimeError(args)
'''


class StopSafety(unittest.TestCase):
    def fixture(self, d, scenario):
        tools = d / 'tools'
        tools.mkdir()
        for name in ('init', 'uci', 'dnsmasq', 'firewall', 'policy', 'redirects', 'journal', 'ip', 'nft', 'logger'):
            p = tools / name
            p.write_text(MOCK)
            p.chmod(0o755)
        return tools, {**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH'],
                       'TEST_ROOT': str(d), 'TEST_SCENARIO': scenario}

    def test_cli_always_attempts_stop_and_reports_failures(self):
        source = (ROOT / 'usr/bin/xray-lab').read_text()
        body = source.split('\nstop)\n', 1)[1].split('\n    ;;', 1)[0]
        for scenario in ('success', 'uci', 'disable', 'stop', 'still-running'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                d = Path(temp)
                tools, env = self.fixture(d, scenario)
                body_local = body.replace('/etc/init.d/xray_core', str(tools / 'init')).replace('/usr/bin/xray-lab-subscription-journal', str(tools / 'journal'))
                result = subprocess.run(['sh', '-c', 'set -eu\n' + body_local], env=env,
                                        capture_output=True, text=True, timeout=5)
                events = (d / 'events').read_text()
                self.assertIn('init stop\n', events)
                self.assertIn('uci set xray_core.general.fx_start_authorized=0\n', events)
                self.assertEqual(result.returncode == 0, scenario == 'success', result.stderr)
                if scenario != 'success':
                    self.assertNotIn('службы очистки завершились без ошибок', result.stdout)

    def test_init_cleanup_attempts_dns_and_firewall_independently(self):
        source = (ROOT / 'etc/init.d/xray_core').read_text()
        for scenario in ('success', 'dnsmasq', 'firewall', 'policy', 'all'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                d = Path(temp)
                tools, env = self.fixture(d, scenario)
                instance = d / 'dnsmasq.instance.d'
                instance.mkdir()
                (instance / 'xray.conf').write_text('server=127.0.0.1#10553')
                (instance / 'other.conf').write_text('unrelated')
                generated = d / 'generated'
                generated.mkdir()
                (generated / '01_firewall_include.nft').write_text('test')
                local = source.replace('/usr/bin/xray-lab-local-policy', str(tools / 'policy'))
                local = local.replace('/usr/bin/xray-lab-redirects', str(tools / 'redirects'))
                local = local.replace('/etc/init.d/dnsmasq', str(tools / 'dnsmasq'))
                local = local.replace('/etc/init.d/firewall', str(tools / 'firewall'))
                local = local.replace('/tmp/dnsmasq', str(d / 'dnsmasq'))
                local = local.replace('/var/etc/xray/', str(generated) + '/')
                script = d / 'init-functions'
                script.write_text(local)
                result = subprocess.run(['sh', '-c', '. "$1"; flush_when_disable', '_', str(script)],
                                        env=env, capture_output=True, text=True, timeout=5)
                events = (d / 'events').read_text()
                self.assertNotIn('redirects down', events) # proxy stop must not teach client bypass routes
                self.assertIn('dnsmasq restart\n', events)
                self.assertIn('firewall restart\n', events)
                self.assertFalse((instance / 'xray.conf').exists())
                self.assertEqual((instance / 'other.conf').read_text(), 'unrelated')
                self.assertFalse((generated / '01_firewall_include.nft').exists())
                self.assertEqual(result.returncode == 0, scenario == 'success', result.stderr)
                if scenario in ('firewall', 'all'):
                    self.assertIn('nft flush chain inet fw4 xray_prerouting\n', events)
                    self.assertIn('nft flush chain inet fw4 fx_dns_redirect\n', events)
                else:
                    self.assertNotIn('nft flush', events)


if __name__ == '__main__':
    unittest.main()
