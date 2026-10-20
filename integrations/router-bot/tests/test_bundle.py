import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('stage_bot',ROOT/'scripts/stage-bot-bundle.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)


class BundleTests(unittest.TestCase):
    def test_package_contains_only_public_code_and_verified_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)/'sdk/package/xtlsprovpn/files/usr/share/xray/bot'
            stage.stage(dest)
            self.assertEqual({p.name for p in dest.iterdir()},set(stage.FILES)|{'bundle.sha256'})
            for line in (dest/'bundle.sha256').read_text().splitlines():
                digest,name=line.split()
                self.assertEqual(hashlib.sha256((dest/name).read_bytes()).hexdigest(),digest)
            for forbidden in ('device-id','profile.json','id_ed25519','telegram_token','authorized_keys','subscription.json'):
                self.assertFalse((dest/forbidden).exists())
            self.assertIn('/etc/xtlspro-bot/',(ROOT/'package/xtlsprovpn/files/lib/upgrade/keep.d/xtlsprovpn-bot').read_text())

    def test_stager_refuses_arbitrary_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)/'important';dest.mkdir();(dest/'keep').write_text('keep')
            with self.assertRaises(ValueError):stage.stage(dest)
            self.assertEqual((dest/'keep').read_text(),'keep')


@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bundle=self.root/'sdk/package/xtlsprovpn/files/usr/share/xray/bot';stage.stage(self.bundle)
        self.dest=self.root/'private';self.dest.mkdir()
        for name,body in [('profile.json','PUBLIC-PROFILE'),('device-id','DEVICE'),('authorized_keys','ORIGINAL-ADMIN-KEY')]:
            (self.dest/name).write_text(body)
        self.before={name:(self.dest/name).read_bytes() for name in ('profile.json','device-id','authorized_keys')}
        self.old={name:('OLD '+name).encode() for name in ('ssh.uc','ssh-entry','admin.uc','admin-worker','updates.uc','update-worker','onboard.uc')}
        for name,body in self.old.items():(self.dest/name).write_bytes(body)
        run=self.root/'run'
        for name in ('xtlspro-bot-admin','xtlspro-netbird','xray-lab-control'):(run/name).mkdir(parents=True)
        mods=self.root/'mods';mods.mkdir();(mods/'uci.uc').write_text('export function cursor(){return {};};')
        bins=self.root/'bin';bins.mkdir()
        native=shutil.which('ucode')
        compiler=bins/'ucode';compiler.write_text('#!/bin/sh\nexec '+native+' -L '+str(mods)+' "$@"\n');compiler.chmod(0o700)
        self.env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'])
        self.source=self.bundle/'refresh.sh'
        self.source.write_text(self.source.read_text().replace('/etc/xtlspro-bot',str(self.dest)).replace('/var/run',str(run)).replace('/root/xtls-before-bot-refresh.',str(self.root/'backup.')))
        self.bins=bins

    def call(self):
        return subprocess.run(['sh',str(self.source)],env=self.env,capture_output=True,text=True,timeout=10)

    def test_refresh_updates_code_but_preserves_binding_and_keys(self):
        result=self.call();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for name,body in self.before.items():self.assertEqual((self.dest/name).read_bytes(),body)
        self.assertEqual((self.dest/'ssh.uc').read_bytes(),(self.bundle/'ssh.uc').read_bytes())
        self.assertEqual((self.dest/'ssh-entry').stat().st_mode&0o777,0o700)
        self.assertEqual((self.dest/'onboard.uc').stat().st_mode&0o777,0o600)

    def test_partial_commit_failure_restores_all_previous_helpers(self):
        mv=self.bins/'mv';mv.write_text('#!/bin/sh\ncase "$1" in *ssh.uc.new) exit 1;; esac\nexec /bin/mv "$@"\n');mv.chmod(0o700)
        result=self.call();self.assertNotEqual(result.returncode,0)
        for name,body in self.old.items():self.assertEqual((self.dest/name).read_bytes(),body)
        for name,body in self.before.items():self.assertEqual((self.dest/name).read_bytes(),body)

    def test_bad_bundle_refused_before_replacing_code(self):
        (self.bundle/'onboard.uc').write_text('this is invalid syntax!')
        self.assertNotEqual(self.call().returncode,0)
        for name,body in self.old.items():self.assertEqual((self.dest/name).read_bytes(),body)
