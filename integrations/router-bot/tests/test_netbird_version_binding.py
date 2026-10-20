import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'package/xtlsprovpn/files/usr/share/xray/lab/netbird.uc'


@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class NativeBindingTests(unittest.TestCase):
    def test_changed_catalog_refused_before_install_and_unset_env_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'binary').touch();(root/'service').touch()
            mods=root/'mods';mods.mkdir()
            (mods/'uci.uc').write_text('export function cursor(){return {};};')
            source=SOURCE.read_text().split('let mode=ARGV[0]')[0]
            source=source.replace("const BIN='/usr/bin/netbird';", "const BIN='"+str(root/'binary')+"';")
            source=source.replace("const SERVICE='/etc/init.d/netbird';", "const SERVICE='"+str(root/'service')+"';")
            source=source.replace('let c=package_catalog(true);',"let c={available:'0.79.0-r1',update_available:false};")
            path=root/'test.uc';path.write_text(source+'\nprint(upgrade_package());\n')
            for expected,ok in [('0.78.1-r1',False),('0.79.0-r1',True),('',True)]:
                result=subprocess.run(['ucode','-L',str(mods),str(path)],env=dict(os.environ,FX_NETBIRD_EXPECTED_VERSION=expected),capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode==0,ok,result.stdout+result.stderr)
                if not ok:self.assertIn('Каталог NetBird изменился',result.stderr)
