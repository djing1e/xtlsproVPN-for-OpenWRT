import os, shutil, subprocess, tempfile, unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI'+'A'*43

@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
        self.auth=self.r/'authorized_keys';self.original='ssh-rsa EXISTING-ADMIN-KEY administrator\n';self.auth.write_text(self.original)
        self.key=self.r/'bot.pub';self.key.write_text(KEY+' bot\n')
        self.shadow=self.r/'shadow';self.shadow.write_text('root:NONEMPTY-TEST-FIXTURE:0:0:99999:7:::\n')
        src=self.r/'source';src.mkdir()
        for name in ['ssh.uc','ssh-entry','admin.uc','admin-worker']:shutil.copy(BASE/'router'/name,src/name)
        controller=self.r/'controller';controller.touch();controller.chmod(0o700)
        text=(BASE/'router/install.sh').read_text().replace('/etc/dropbear/authorized_keys',str(self.auth)).replace('/etc/xtlspro-bot',str(self.r/'deployed')).replace('/root/xtls-before-bot-bridge.',str(self.r/'backup.')).replace('/usr/bin/xray-lab-control',str(controller)).replace('/etc/shadow',str(self.shadow))
        self.installer=src/'install.sh';self.installer.write_text(text)
        bins=self.r/'bin';bins.mkdir()
        for name,body in [('id','echo 0'),('chown',':')]:
            p=bins/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o700)
        self.env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'])
    def run_install(self,ok=True):
        p=subprocess.run(['sh',str(self.installer),str(self.key)],env=self.env,capture_output=True,text=True)
        self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr)
    def test_install_and_repeat_preserve_admin_and_force_command(self):
        self.run_install();first=self.auth.read_text();self.run_install();self.assertEqual(first,self.auth.read_text())
        self.assertTrue(first.startswith(self.original));self.assertEqual(first.count(KEY),1)
        self.assertIn('command="'+str(self.r/'deployed')+'/ssh-entry",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty '+KEY,first)
        self.assertEqual((self.r/'deployed/ssh-entry').stat().st_mode&0o777,0o700)
        self.assertEqual((self.r/'deployed/ssh.uc').stat().st_mode&0o777,0o600)
        self.assertTrue(any((p/'authorized_keys').read_text()==self.original for p in self.r.glob('backup.*')))
    def test_multiple_keys_cannot_inject_unrestricted_authorization(self):
        self.key.write_text(KEY+' first\n'+KEY+' second\n')
        self.run_install(False);self.assertEqual(self.auth.read_text(),self.original)
        self.assertFalse((self.r/'deployed').exists())
    def test_existing_unrestricted_key_is_not_silently_accepted(self):
        self.auth.write_text(self.original+KEY+' old-unrestricted\n');before=self.auth.read_text()
        self.run_install(False);self.assertEqual(self.auth.read_text(),before)
    def test_bad_key_and_missing_auth_refused_before_changes(self):
        self.key.write_text('ssh-rsa not-the-expected-key\n');self.run_install(False)
        self.assertEqual(self.auth.read_text(),self.original)
        self.auth.unlink();self.run_install(False);self.assertFalse((self.r/'deployed').exists())
    def test_first_key_and_empty_file_supported(self):
        self.auth.unlink();self.run_install()
        self.assertIn(KEY,self.auth.read_text())
        self.assertEqual(self.auth.stat().st_mode&0o777,0o600)
        self.assertTrue(any((p/'authorized_keys.absent').exists() for p in self.r.glob('backup.*')))
        self.auth.write_text('');self.run_install();self.assertIn(KEY,self.auth.read_text())
    def test_directory_or_dangling_symlink_is_not_replaced(self):
        self.auth.unlink();self.auth.mkdir();self.run_install(False);self.assertTrue(self.auth.is_dir())
        self.auth.rmdir();self.auth.symlink_to(self.r/'missing');self.run_install(False)
        self.assertTrue(self.auth.is_symlink());self.assertFalse((self.r/'missing').exists())
    def test_empty_or_missing_root_password_record_rejected(self):
        for value in ['root::0:0:99999:7:::\n','other:x:0:0:99999:7:::\n','']:
            self.shadow.write_text(value);self.run_install(False)
            self.assertEqual(self.auth.read_text(),self.original)
            self.assertFalse((self.r/'deployed').exists())

if __name__=='__main__':unittest.main()
