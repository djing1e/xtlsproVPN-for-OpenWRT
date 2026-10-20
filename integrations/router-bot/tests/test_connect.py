import base64,hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_fleet as ft

spec=importlib.util.spec_from_file_location('connect',Path(__file__).resolve().parents[1]/'server/connect.py')
c=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'fleet':ft.f,'bot':ft.pilot.b}):spec.loader.exec_module(c)
FINGERPRINT='esLC1GpVsAr8dflLXB+KOlwEzPeccZp30F+F/7FMsD8'
CODE='xtls-pair-v1:100.124.249.61:22:'+FINGERPRINT
PROFILE={'schema':1,'profile_id':ft.PROFILE,'bot_public_key':ft.RESCUE,'rescue_host':'87.239.135.108','rescue_port':62152,'rescue_host_key':ft.KEY}

class PairingTests(unittest.TestCase):
    def test_short_code_has_host_port_and_cryptographic_fingerprint(self):
        self.assertEqual(c.fingerprint(ft.KEY),FINGERPRINT)
        self.assertEqual(c.pairing(CODE),{'host':'100.124.249.61','port':22,'fingerprint':FINGERPRINT})
        for bad in [CODE+';id',CODE+'\n',CODE.replace(':22:',':0:'),CODE.replace('100.124.249.61','1.1.1.1'),CODE.replace('100.124.249.61','100.999.1.1'),'x'*151]:
            with self.assertRaises(ft.pilot.b.SafeError):c.pairing(bad)
    def test_scanned_key_must_match_operator_fingerprint(self):
        self.assertEqual(c.scanned_key('# banner\n100.124.249.61 '+ft.KEY+'\n',FINGERPRINT),ft.KEY)
        for bad in ['100.124.249.61 '+ft.RESCUE+'\n','', '100.124.249.61 '+ft.KEY+' extra\n']:
            with self.assertRaises(ft.pilot.b.SafeError):c.scanned_key(bad,FINGERPRINT)
    def test_command_embeds_only_public_profile_and_pinned_bootstrap(self):
        cmd=c.router_command({**PROFILE,'telegram_token':'SECRET','private_key':'SECRET'})
        self.assertTrue(cmd.startswith('clear; '));self.assertIn(c.BOOTSTRAP_REF,cmd);self.assertIn(c.BOOTSTRAP_SHA,cmd)
        token=cmd.split('xtls-profile-v1:')[1].split()[0]
        self.assertEqual(json.loads(base64.b64decode(token)),PROFILE)
        self.assertNotIn('SECRET',cmd);self.assertIn('mktemp -d',cmd)
        subprocess.run(['sh','-n','-c',cmd],check=True)
    def test_primary_only_pin_never_writes_a_fake_rescue_mapping(self):
        pins=ft.f.pinned('',ft.P,None)
        self.assertIn(ft.P['host']+' '+ft.KEY,pins)
        self.assertNotIn('127.0.0.1',pins)

class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.known=self.root/'known_hosts';self.known.write_text(ft.P['host']+' '+ft.KEY+'\n')
        self.config={'known_hosts':str(self.known),'routers':{'lab':{'host':ft.P['host'],'port':22,'name':'LAB'}}}
        self.patchers=[patch.object(c,'scan_key',return_value=ft.KEY),patch.object(c.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())),patch.object(c.fleet,'remote',return_value=ft.P)]
        self.mocks=[p.start() for p in self.patchers]
        for p in self.patchers:self.addCleanup(p.stop)
    def test_resolve_uses_temporary_pin_preserves_known_hosts_and_adopts_lab(self):
        before=self.known.read_bytes()
        p=c.resolve(self.config,c.pairing(CODE),PROFILE)
        self.assertEqual(p,ft.P);self.assertEqual(c.legacy_router(self.config,p),'lab')
        self.assertEqual(self.known.read_bytes(),before)
        self.assertEqual(list(self.root.glob('.connect-probe-*')),[])
        with patch.object(c.fleet,'enroll') as enroll:
            c.complete(self.config,CODE,PROFILE)
            enroll.assert_called_once_with(self.config,ft.P,'lab',None)
    def test_different_profile_or_endpoint_never_enrolls(self):
        for response in [{**ft.P,'profile_id':ft.DEVICE},{**ft.P,'host':'100.124.0.2'},{**ft.P,'host_key':ft.RESCUE}]:
            with patch.object(c.fleet,'remote',return_value=response),patch.object(c.fleet,'enroll') as enroll:
                with self.assertRaises(ft.pilot.b.SafeError):c.complete(self.config,CODE,PROFILE)
                enroll.assert_not_called()
            self.assertEqual(list(self.root.glob('.connect-probe-*')),[])
    def test_existing_conflicting_pin_never_connects_or_overwrites(self):
        self.known.write_text(ft.P['host']+' '+ft.RESCUE+'\n')
        with self.assertRaises(ft.pilot.b.SafeError):c.resolve(self.config,c.pairing(CODE),PROFILE)
        self.mocks[-1].assert_not_called()
        self.assertIn(ft.RESCUE,self.known.read_text())
    def test_failed_fingerprint_never_calls_identity(self):
        self.mocks[0].side_effect=ft.pilot.b.SafeError('Mismatch')
        with self.assertRaises(ft.pilot.b.SafeError):c.resolve(self.config,c.pairing(CODE),PROFILE)
        self.mocks[-1].assert_not_called()
