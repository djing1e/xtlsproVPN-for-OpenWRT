import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=('etc/init.d/xray_core','usr/share/xray/lab/dns_forward.uc','usr/share/xray/lab/dns_query.uc')

class DNSForwardInstaller(unittest.TestCase):
    def test_verified_code_only_install_rejects_bad_input_and_rolls_back_write_failure(self):
        for case in ('ok','unknown','corrupt','wrong-apk','non-root','write-failure'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                d=Path(temp);root=d/'root';bundle=d/'bundle';bins=d/'bin';bins.mkdir();bundle.mkdir()
                for name in FILES:
                    target=bundle/'files'/name;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(ROOT/'tests/fixtures/dns-forward-144/xray_core' if name=='etc/init.d/xray_core' else ROOT/'package/xtlsprovpn/files'/name,target)
                shutil.copy2(ROOT/'scripts/fix-dns-forwarding-143.sh',bundle/'install.sh')
                for name in ('etc/init.d/xray_core','usr/share/xray/lab/dns_query.uc'):
                    target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(ROOT/'tests/fixtures/dns-forward-143'/Path(name).name,target)
                (root/'root').mkdir();(root/'etc/config').mkdir();(root/'etc/config/dhcp').write_text('original DHCP')
                shutil.copy2(ROOT/'package/xtlsprovpn/files/usr/share/xray/lab/dns_wire.mjs',root/'usr/share/xray/lab/dns_wire.mjs')
                if case=='unknown':(root/FILES[0]).write_text('administrator custom code')
                if case=='corrupt':(bundle/'files'/FILES[1]).write_text('tampered')
                for name,body in {'id':'echo '+('1000' if case=='non-root' else '0'),
                                  'apk':"echo xtlsprovpn-"+('1.4.2' if case=='wrong-apk' else '1.4.3')+'-r1',
                                  'ucode':'exit 0',
                                  'mv':'''if [ "$TEST_FAIL" = 1 ] && [ "${1##*/}" = dns_forward.uc.dns-fix-new ];then exit 1;fi
exec /bin/mv "$@"'''} .items():
                    p=bins/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
                before={name:(root/name).read_bytes() for name in (FILES[0],FILES[2])}
                env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'],FX_DNS_HOTFIX_ROOT=str(root),TEST_FAIL='1' if case=='write-failure' else '0')
                for iteration in range(2 if case=='ok' else 1):
                    p=subprocess.run(['sh',str(bundle/'install.sh')],env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(p.returncode==0,case=='ok',p.stdout+p.stderr)
                self.assertEqual((root/'etc/config/dhcp').read_text(),'original DHCP')
                if case=='ok':
                    for name in FILES:self.assertEqual((root/name).read_bytes(),(bundle/'files'/name).read_bytes())
                    self.assertTrue(list((root/'root').glob('xtls-before-dns-forward.*')))
                else:
                    for name,data in before.items():self.assertEqual((root/name).read_bytes(),data)
                    self.assertFalse((root/FILES[1]).exists())
                self.assertFalse(list(root.rglob('*.dns-fix-new')))

if __name__=='__main__':unittest.main()
