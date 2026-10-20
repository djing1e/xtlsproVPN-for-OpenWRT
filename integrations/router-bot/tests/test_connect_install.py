import importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('connect_install',Path(__file__).resolve().parents[1]/'server/install-connect.py')
i=importlib.util.module_from_spec(spec);spec.loader.exec_module(i)

class ConnectInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.app=self.root/'app';self.app.mkdir();self.source=self.root/'source';self.source.mkdir()
        self.alias=self.root/'local/sbin/xtls-router-add';self.alias.parent.mkdir(parents=True)
        self.config=self.root/'config.json';self.token=self.root/'token';self.key=self.root/'private';self.known=self.root/'known'
        self.config.write_text(json.dumps({'ssh_key':str(self.key),'known_hosts':str(self.known)}))
        for path in [self.token,self.key,self.known,self.app/'bot.py']:path.write_text('PRESERVED-'+path.name)
        for name in i.FILES:
            (self.source/name).write_text('NEW = 1\n' if name.endswith('.py') else '#!/bin/sh\nexit 0\n')
            target=self.alias if name=='xtls-router-add' else self.app/name
            target.write_text('OLD '+name);target.chmod(0o644)
        self.before={p:p.read_bytes() for p in [self.config,self.token,self.key,self.known,self.app/'bot.py',self.alias,*[self.app/n for n in i.FILES if n!='xtls-router-add']]}
        mkdtemp=tempfile.mkdtemp
        patches=[patch.object(i,'APP',self.app),patch.object(i,'ALIAS',self.alias),patch.object(i,'CONFIG',self.config),patch.object(i,'TOKEN',self.token),patch.object(i,'LOCK',self.root/'lock'),patch.object(i.os,'geteuid',return_value=0),patch.object(i.tempfile,'mkdtemp',side_effect=lambda **kw:mkdtemp(dir=self.root))]
        for p in patches:p.start();self.addCleanup(p.stop)
    def test_install_preserves_identity_and_does_not_touch_bot_code(self):
        i.install(self.source)
        for path in [self.config,self.token,self.key,self.known,self.app/'bot.py']:self.assertEqual(path.read_bytes(),self.before[path])
        self.assertEqual(self.alias.stat().st_mode&0o777,0o755)
        self.assertEqual((self.app/'connect.py').read_bytes(),(self.source/'connect.py').read_bytes())
    def test_partial_write_rolls_back_all_operator_helpers(self):
        original=i.atomic;failed=False
        def atomic(path,body,mode):
            nonlocal failed
            if path.name=='connect.py' and not failed:failed=True;raise OSError('test failure')
            return original(path,body,mode)
        with patch.object(i,'atomic',side_effect=atomic):
            with self.assertRaises(OSError):i.install(self.source)
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
    def test_invalid_source_never_changes_installed_files(self):
        (self.source/'connect.py').write_text('invalid python!')
        with self.assertRaises(SyntaxError):i.install(self.source)
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
