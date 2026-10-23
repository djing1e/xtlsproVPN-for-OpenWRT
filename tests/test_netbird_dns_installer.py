import hashlib, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['etc/init.d/xray_core','usr/bin/xray-netbird-guard','usr/share/xray/lab/netbird.uc',
       'usr/bin/xray-dns-bind','usr/share/xray/lab/dns_bind.uc','etc/uci-defaults/94-xtls-dns-bind']
class Installer(unittest.TestCase):
    def test_verify_idempotence_and_rollback(self):
        for case in ('ok','corrupt','unknown','wrong-apk','non-root','write-failure'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                d=Path(tmp);r=d/'root';b=d/'bundle';bins=d/'bin';bins.mkdir();b.mkdir()
                (r/'root').mkdir(parents=True);(r/'etc/config').mkdir(parents=True);(r/'etc/config/dhcp').write_text('original')
                for name in FILES:
                    p=b/'files'/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'package/xtlsprovpn/files'/name,p)
                before={}
                for name in FILES[:3]:
                    data=subprocess.check_output(['git','show','a0870c13b0847d3b59a79b2d59969c8800418b74:package/xtlsprovpn/files/'+name],cwd=ROOT)
                    p=r/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);before[name]=data
                (b/'FILES.sha256').write_text(''.join(hashlib.sha256((b/'files'/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in FILES))
                shutil.copy2(ROOT/'scripts/fix-netbird-dns-144.sh',b/'install.sh')
                if case=='unknown':(r/FILES[0]).write_text('custom');before[FILES[0]]=b'custom'
                if case=='corrupt':(b/'files'/FILES[-1]).write_text('corrupt')
                for name,body in {'id':'echo '+('1000' if case=='non-root' else '0'),
                    'apk':'echo xtlsprovpn-'+('1.4.3' if case=='wrong-apk' else '1.4.4')+'-r1',
                    'ucode':'exit 0',
                    'mv':'if [ "$TEST_FAIL" = 1 ] && [ "${1##*/}" = xray-dns-bind.netbird-dns-new ];then exit 1;fi\nexec /bin/mv "$@"'}.items():
                    p=bins/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
                env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'],FX_DNS_HOTFIX_ROOT=str(r),TEST_FAIL='1' if case=='write-failure' else '0')
                for _ in range(2 if case=='ok' else 1):
                    p=subprocess.run(['sh',str(b/'install.sh')],env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(p.returncode==0,case=='ok',p.stdout+p.stderr)
                self.assertEqual((r/'etc/config/dhcp').read_text(),'original')
                if case=='ok':
                    for name in FILES:self.assertEqual((r/name).read_bytes(),(b/'files'/name).read_bytes())
                else:
                    for name,data in before.items():self.assertEqual((r/name).read_bytes(),data)
                    for name in FILES[3:]:self.assertFalse((r/name).exists())
                self.assertFalse(list(r.rglob('*.netbird-dns-new')))
if __name__=='__main__':unittest.main()
