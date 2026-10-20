import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import test_telegram as pilot

spec = importlib.util.spec_from_file_location('rescue_enroll', Path(__file__).resolve().parents[1] / 'server/enroll_rescue.py')
e = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'bot': pilot.b}):
    spec.loader.exec_module(e)

KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGvOWJsdfLieCYoFuZ9MB2UgQHh6s+0yfZm+VVdLR5Ox'


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.config = {'routers': {'lab': {'host': '100.124.0.1', 'port': 22}}}
        self.known = '100.124.0.1 ' + KEY + '\n'

    def test_pin_and_repeat_are_idempotent(self):
        config, known = e.enrolled(self.config, self.known, 'lab', 22002, KEY)
        self.assertEqual(config['routers']['lab']['rescue'], {'host': '127.0.0.1', 'port': 22002})
        self.assertEqual(known, e.enrolled(config, known, 'lab', 22002, KEY)[1])

    def test_wrong_router_key_refused(self):
        with self.assertRaises(pilot.b.SafeError):
            e.enrolled(self.config, '', 'lab', 22002, KEY)

    def test_existing_conflicting_pin_refused(self):
        with self.assertRaises(pilot.b.SafeError):
            e.enrolled(self.config, self.known + '[127.0.0.1]:22002 ssh-ed25519 OTHER\n', 'lab', 22002, KEY)

    def test_other_router_port_refused(self):
        self.config['routers']['other'] = {'rescue': {'port': 22002}}
        with self.assertRaises(pilot.b.SafeError):
            e.enrolled(self.config, self.known, 'lab', 22002, KEY)

    def test_invalid_key_rejected(self):
        for key in ('ssh-ed25519 BAD', KEY + ' comment', 'ssh-rsa XXX'):
            with self.assertRaises(pilot.b.SafeError):
                e.enrolled(copy.deepcopy(self.config), self.known, 'lab', 22002, key)
