import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import test_telegram as pilot

b = pilot.b


def reply(data=None, code=0):
    return SimpleNamespace(returncode=code, stdout=json.dumps({'schema': 1, 'ok': True, 'data': data or {}}).encode())


def failed():
    return SimpleNamespace(returncode=255, stdout=b'', stderr=b'SECRET')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.config = {'ssh_key': '/key', 'known_hosts': '/known'}
        self.router = {'host': '100.124.0.1', 'port': 22, 'rescue': {'host': '127.0.0.1', 'port': 22002}}
        self.bridge = b.Bridge(self.config)

    def test_primary_read_does_not_open_rescue(self):
        with patch.object(b.subprocess, 'run', return_value=reply()) as run:
            self.assertEqual(self.bridge.call(self.router, 'xtlsbot-v1 status')['_transport'], 'netbird')
        self.assertEqual(run.call_count, 1)

    def test_read_and_job_fallback_pin_loopback(self):
        for command in ('xtlsbot-v1 status', 'xtlsbot-v1 locations', 'xtlsbot-v1 diagnostics', 'xtlsbot-v1 job ' + pilot.JOB):
            with patch.object(b.subprocess, 'run', side_effect=[failed(), reply()]) as run:
                self.assertEqual(self.bridge.call(self.router, command)['_transport'], 'rescue')
            args = run.call_args.args[0]
            self.assertIn('root@127.0.0.1', args)
            self.assertIn('22002', args)
            self.assertIn('StrictHostKeyChecking=yes', args)
            self.assertIn('GlobalKnownHostsFile=/dev/null', args)
            self.assertIn('UserKnownHostsFile=/known', args)

    def test_mutation_fallback_only_before_dispatch(self):
        with patch.object(b.subprocess, 'run', side_effect=[failed(), reply(), reply({'accepted': True})]) as run:
            self.assertTrue(self.bridge.call(self.router, 'xtlsbot-v1 auto')['accepted'])
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], ['xtlsbot-v1 status', 'xtlsbot-v1 status', 'xtlsbot-v1 auto'])

    def test_ambiguous_mutation_never_replayed(self):
        for error in (failed(), subprocess.TimeoutExpired('ssh', 23)):
            with patch.object(b.subprocess, 'run', side_effect=[reply(), error]) as run:
                with self.assertRaises(b.SafeError) as caught:
                    self.bridge.call(self.router, 'xtlsbot-v1 select cfg3db316')
            self.assertEqual(run.call_count, 2)
            self.assertIn('повторно не отправлена', str(caught.exception))

    def test_protocol_rejection_not_retried(self):
        result = SimpleNamespace(returncode=1, stdout=b'{"schema":1,"ok":false,"error":{"code":"busy"}}')
        with patch.object(b.subprocess, 'run', return_value=result) as run:
            with self.assertRaises(b.SafeError):
                self.bridge.call(self.router, 'xtlsbot-v1 status')
        self.assertEqual(run.call_count, 1)

    def test_both_unreachable_redacts_errors(self):
        with patch.object(b.subprocess, 'run', return_value=failed()) as run:
            with self.assertRaises(b.SafeError) as caught:
                self.bridge.call(self.router, 'xtlsbot-v1 auto')
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(c.args[0][-1] == 'xtlsbot-v1 status' for c in run.call_args_list))

    def test_bad_protocol_does_not_fallback(self):
        with patch.object(b.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'garbage')) as run:
            with self.assertRaises(b.SafeError):
                self.bridge.call(self.router, 'xtlsbot-v1 status')
        self.assertEqual(run.call_count, 1)

    def test_config_restricts_rescue_and_unique_ports(self):
        config = {**self.config, 'database': '/db', 'admin_id': 1, 'bot_username': 'xtlsproroutbot', 'routers': {'lab': self.router}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(config))
            b.load_config(path)
            for rescue in ({'host': '8.8.8.8', 'port': 22002}, {'host': '127.0.0.1', 'port': True}, {'host': '127.0.0.1', 'port': 22}, {'host': '127.0.0.1', 'port': 22002, 'ssh_key': '/other'}):
                config['routers']['lab']['rescue'] = rescue
                path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    b.load_config(path)
            config['routers']['lab']['rescue'] = {'host': '127.0.0.1', 'port': 22002}
            config['routers']['second'] = dict(self.router)
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                b.load_config(path)
