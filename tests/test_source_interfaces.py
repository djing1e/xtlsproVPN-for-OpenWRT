import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'package/xtlsprovpn/files/usr/share/xray'


@unittest.skipUnless(shutil.which('ucode'), 'ucode runtime required')
class SourceInterfaces(unittest.TestCase):
    def resolve(self, network, explicit=None, saved='br-old'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / 'network.json'
            fixture.write_text(json.dumps(network))
            script = root / 'run.uc'
            script.write_text(
                "import { resolve_sources } from '" + str(LIB/'lab/source_interfaces.mjs') + "';\n"
                "printf('%J',resolve_sources(" + json.dumps(explicit or []) + ","
                + json.dumps({'lab_iface': saved}) + "));\n")
            return subprocess.run(['ucode', str(script)], capture_output=True, text=True,
                                  env=dict(os.environ, XRAY_LAB_NETWORK_JSON=str(fixture)))

    def test_live_lan_replaces_stale_profile_and_allows_ap_gateway(self):
        for device in ['br-lan', 'br-clients', 'eth0.10']:
            with self.subTest(device=device):
                result = self.resolve({'up': True, 'l3_device': device,
                                       'route': [{'target': '0.0.0.0', 'nexthop': '192.168.6.1'}]})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [device])

    def test_manual_multiple_sources_win(self):
        result = self.resolve({'up': True, 'l3_device': 'br-lan'}, ['br-guest', 'br-iot'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['br-guest', 'br-iot'])

    def test_saved_profile_during_netifd_startup(self):
        for network in [None, {}, {'up': False, 'l3_device': 'br-lan'},
                        {'up': True, 'l3_device': 'lo'}, {'up': True, 'l3_device': 'invalid;name'}]:
            with self.subTest(network=network):
                result = self.resolve(network)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), ['br-old'])

    def test_missing_lan_reports_actionable_error(self):
        result = self.resolve({}, saved='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Выберите его', result.stderr)

    def test_config_and_firewall_use_same_resolved_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'uci.uc').write_text("export function cursor(dir) { return {load:function(p){},get_all:function(p){return {general:{lab_iface:'br-old',tproxy_ifaces_v4:['br-old']}};}};};")
            network = root/'network.json'
            network.write_text(json.dumps({'up': True, 'l3_device': 'br-lan'}))
            prefs = root/'prefs.json'
            runner = root/'run.uc'
            runner.write_text("import { load_config } from '" + str(LIB/'common/config.mjs') + "'; printf('%J',load_config().general);")
            for explicit, expected in [([], ['br-lan']), (['br-guest', 'br-iot'], ['br-guest', 'br-iot'])]:
                prefs.write_text(json.dumps({'sources': explicit}))
                result = subprocess.run(['ucode', '-L', str(root), str(runner)],
                    capture_output=True, text=True, env=dict(os.environ,
                    XRAY_LAB_NETWORK_JSON=str(network), FX_DNS_PREFS_JSON=str(prefs)))
                self.assertEqual(result.returncode, 0, result.stderr)
                general = json.loads(result.stdout)
                self.assertEqual(general['lab_iface'], expected[0])
                self.assertEqual(general['tproxy_ifaces_v4'], expected)
            template = (LIB/'firewall_include.ut').read_text()
            self.assertIn('const source_devices=general.tproxy_ifaces_v4', template)

    def test_netifd_device_fallback(self):
        result = self.resolve({'up': True, 'device': 'br-lan'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['br-lan'])


if __name__ == '__main__':
    unittest.main()
