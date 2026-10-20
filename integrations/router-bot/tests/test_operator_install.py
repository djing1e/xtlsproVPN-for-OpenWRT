import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_backup as bt
import test_upgrade as ut

SERVER=Path(__file__).resolve().parents[1]/'server'
spec=importlib.util.spec_from_file_location('operator_install',SERVER/'install-operator.py')
installer=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'backup':bt.backup,'upgrade':ut.upgrade}):spec.loader.exec_module(installer)

class OperatorInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir();self.app=self.root/'app';self.app.mkdir();self.units=self.root/'units';self.units.mkdir()
        for name in (*installer.HELPERS,'bot.py','upgrade.py'):(self.source/name).write_text('NEW = True\n')
        for name in installer.UNITS_NAMES:(self.source/name).write_text('[Unit]\n')
        self.bot=self.app/'bot.py';self.bot.write_text('old-bot')
        self.before={self.bot:b'old-bot'}
        for name in installer.HELPERS:
            path=self.app/name;path.write_text('old-'+name);self.before[path]=path.read_bytes()
        mkdtemp=tempfile.mkdtemp
        self.calls=[]
        def run(args,**kw):
            self.calls.append(args)
            return SimpleNamespace(returncode=3 if 'is-active' in args else 0)
        patches=[patch.object(installer,'APP',self.app),patch.object(installer,'UNITS',self.units),patch.object(installer,'__file__',str(self.source/'install-operator.py')),patch.object(installer.os,'geteuid',return_value=0),patch.object(installer.tempfile,'mkdtemp',side_effect=lambda **kw:mkdtemp(dir=self.root)),patch.object(installer.subprocess,'run',side_effect=run),patch.object(installer.backup,'create',return_value='/backup.gpg'),patch.object(installer.backup,'operator_layout'),patch.object(installer.upgrade,'main',side_effect=lambda:self.bot.write_text('new-bot'))]
        self.mocks=[p.start() for p in patches]
        for p in patches:self.addCleanup(p.stop)
    def test_helpers_and_bot_install_then_activate_fixed_service(self):
        installer.main()
        self.assertEqual(self.bot.read_text(),'new-bot')
        for name in installer.HELPERS:self.assertEqual((self.app/name).read_text(),'NEW = True\n')
        installer.backup.operator_layout.assert_called_once()
        self.assertEqual(installer.backup.create.call_count,2)
    def test_failure_after_bot_upgrade_restores_previous_bot_and_helpers(self):
        installer.backup.operator_layout.side_effect=OSError('test failure')
        with self.assertRaises(OSError):installer.main()
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
        for name in installer.UNITS_NAMES:self.assertFalse((self.units/name).exists())
        self.assertIn(['systemctl','start','xtls-router-bot'],self.calls)
    def test_invalid_source_cannot_replace_live_files(self):
        (self.source/'operator_worker.py').write_text('invalid python!')
        with self.assertRaises(SyntaxError):installer.main()
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
