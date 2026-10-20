import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

BASE = Path(__file__).resolve().parents[1] / 'router'
JOB = '11111111-2222-4333-8444-555555555555'
BOOT = '00000000-0000-4000-8000-000000000001'


@unittest.skipUnless(shutil.which('ucode'), 'host ucode required')
class AdminWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bins = self.root / 'bin'
        self.bins.mkdir()
        self.init = self.root / 'init'
        self.init.mkdir()
        self.run = self.root / 'run'
        self.run.mkdir()
        self.boot = self.root / 'boot'
        self.boot.write_text(BOOT)
        self.uptime = self.root / 'uptime'
        self.uptime.write_text('1000.00 0\n')
        self.markers = self.root / 'markers'
        self.env = dict(os.environ, PATH=str(self.bins) + ':' + os.environ['PATH'])
        self.netbird = self.root / 'netbird.json'
        self.netbird.write_text('{"management":{"connected":true},"signal":{"connected":true}}')
        self.make(self.bins / 'netbird', 'cat ' + str(self.netbird))
        self.make(self.bins / 'uci', "case \"$*\" in *transparent_proxy_enable*|*main.enabled*) echo 1;; *) exit 1;; esac")
        self.make(self.bins / 'sleep', 'exit 0')
        self.make(self.bins / 'reboot', 'echo reboot >> ' + str(self.markers))
        for name in ('netbird', 'xray_core', 'xray_rescue_watch'):
            self.make(self.init / name, 'echo ' + name + ':"$1" >> ' + str(self.markers) + '\nexit 0')
        self.make(self.bins / 'jsonfilter', '''exec python3 - "$@" <<'END'
import json,sys
args=sys.argv[1:]
try:
 d=json.load(open(args[args.index('-i')+1]))
 for key in args[args.index('-e')+1].removeprefix('@.').split('.'):d=d[key]
 print(str(d).lower() if isinstance(d,bool) else d)
except Exception:sys.exit(1)
END''')
        self.make(self.bins / 'xray-lab-control', '''case "$1" in
launch) echo '{"id":"''' + JOB + '''","state":"pending"}';;
job) echo '{"id":"''' + JOB + '''","state":"done"}';;
*) exit 1;; esac''')
        health = self.root / 'health.uc'
        health.write_text("print('{\"proxy_ok\":true}');")
        self.worker = self.root / 'admin-worker'
        self.uc = self.root / 'admin.uc'
        substitutions = {
            '/var/run': str(self.run), '/etc/xtlspro-bot/admin.uc': str(self.uc),
            '/etc/init.d': str(self.init), '/proc/sys/kernel/random/boot_id': str(self.boot),
            '/proc/uptime': str(self.uptime), '/usr/bin/netbird': str(self.bins / 'netbird'),
            '/sbin/reboot': str(self.bins / 'reboot'),
            '/usr/share/xray/lab/control.uc': str(health),
        }
        for source, dest in (('admin.uc', self.uc), ('admin-worker', self.worker)):
            text = (BASE / source).read_text()
            for old, new in substitutions.items():
                text = text.replace(old, new)
            text = text.replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin', 'PATH=' + str(self.bins) + ':' + os.environ['PATH'])
            dest.write_text(text)
            dest.chmod(0o700)

    def make(self, path, body):
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o700)

    def call(self, *args):
        result = subprocess.run([str(self.worker), *args], capture_output=True, text=True, env=self.env, timeout=10)
        return result, json.loads(result.stdout) if result.stdout else None

    def wait_job(self):
        for _ in range(150):
            path = self.run / 'xtlspro-bot-admin/job.json'
            if path.exists():
                job = json.loads(path.read_text())
                if job['state'] in ('done', 'failed'):
                    return job
            time.sleep(.02)
        self.fail('Worker timeout')

    def test_status_whitelist(self):
        result, data = self.call('status')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(set(data), {'boot_id','uptime','job','netbird_connected','netbird_enabled','rescue_ready'})
        self.assertTrue(data['rescue_ready'])

    def test_netbird_and_proxy_real_worker_success(self):
        for action in ('netbird', 'proxy'):
            with self.subTest(action=action):
                result, receipt = self.call('launch', action, JOB if action == 'netbird' else JOB[:-1] + '6')
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertTrue(receipt['accepted'])
                self.assertEqual(self.wait_job()['state'], 'done')
                self.uptime.write_text('1400.00 0\n')
        self.assertIn('netbird:restart', self.markers.read_text())

    def test_cooldown_blocks_second_launch(self):
        self.call('launch', 'netbird', JOB)
        self.wait_job()
        result, data = self.call('launch', 'reboot', JOB[:-1] + '6')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(data['error'], 'cooldown')
        self.assertNotIn('reboot\n', self.markers.read_text())

    def test_wrapper_preferred_without_changing_registration(self):
        self.make(self.init / 'netbird-wrapper', 'echo wrapper:"$1" >> ' + str(self.markers) + '\nexit 0')
        self.call('launch', 'netbird', JOB)
        self.assertEqual(self.wait_job()['state'], 'done')
        self.assertIn('wrapper:restart', self.markers.read_text())
        self.assertNotIn('netbird:restart', self.markers.read_text())

    def test_disabled_netbird_prevents_mutation(self):
        self.make(self.init / 'netbird', 'exit 1')
        result, data = self.call('launch', 'netbird', JOB)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(data['error'], 'netbird_autostart_required')

    def test_reboot_requires_rescue_and_core_autostart(self):
        self.make(self.init / 'xray_rescue_watch', 'exit 1')
        result, data = self.call('launch', 'reboot', JOB)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(data['error'], 'rescue_required')
        self.assertNotIn('reboot\n', self.markers.read_text())

    def test_returning_reboot_is_not_success(self):
        result, data = self.call('launch', 'reboot', JOB)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.wait_job()['state'], 'failed')
        self.assertIn('reboot\n', self.markers.read_text())

    def test_same_request_is_not_reexecuted_after_cooldown(self):
        self.call('launch', 'netbird', JOB)
        self.wait_job()
        self.uptime.write_text('1400.00 0\n')
        result, data = self.call('launch', 'netbird', JOB)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(data['accepted'])
        self.assertEqual(self.markers.read_text().count('netbird:restart'), 1)

    def test_direct_worker_and_injection_rejected(self):
        result, data = self.call('worker', 'netbird', JOB)
        self.assertNotEqual(result.returncode, 0)
        for args in [('launch', 'reboot;id', JOB), ('launch', 'netbird', JOB + ';id')]:
            result, data = self.call(*args)
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.markers.exists())
