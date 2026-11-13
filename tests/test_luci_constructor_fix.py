import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
SCRIPT=ROOT/'scripts/fix-luci-constructor-148.sh'
REL='www/luci-static/resources/view/xray/'

class LuCIConstructorFix(unittest.TestCase):
    def test_verified_install_repeat_and_failure_preserve_files(self):
        old={
            'lab_052':"'use strict';\n'require view.xray.lab_148 as lab';\nreturn lab;\n",
            'settings_052':"'use strict';\n'require view.xray.settings_memory147 as settingsView';\n\nreturn settingsView;\n",
            'settings_transfer2':"'use strict';\n'require view.xray.settings_memory147 as settingsView';\n\nreturn settingsView;\n",
            **{name:"'use strict';\n'require view.xray."+target+" as page';\nreturn page;\n" for name,target in {'dashboard_052':'dashboard_148','diagnostics_updates2':'diagnostics_148','monitoring_compact_052':'monitoring_148'}.items()},
            'settings_memory147':(FILES/REL/'settings_memory147.js').read_text().replace('view.xray.lab_148 as lab','view.xray.lab_052 as lab'),
        }
        for case in ('success','unknown','corrupt','rollback','version'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                r=Path(temp);(r/'root').mkdir();(r/'bin').mkdir();(r/REL).mkdir(parents=True)
                for name,source in old.items():(r/REL/(name+'.js')).write_text(source)
                if case=='unknown':(r/REL/'lab_052.js').write_text('custom UI')
                before={p.name:p.read_bytes() for p in (r/REL).iterdir()}
                def executable(name,source):
                    p=r/'bin'/name;p.write_text('#!/usr/bin/env python3\n'+source);p.chmod(0o755)
                executable('id',"print('0')\n")
                executable('apk',"print("+repr('xtlsprovpn-1.4.7-r1' if case=='version' else 'xtlsprovpn-1.4.8-r1')+")\n")
                executable('curl',f'''import pathlib,sys
r=pathlib.Path({str(r)!r});args=sys.argv[1:]
with (r/'requests').open('a') as f:f.write('download\\n')
url=next(a for a in args if a.startswith('https://'))
source=pathlib.Path({str(FILES)!r})/url.split('/package/xtlsprovpn/files/',1)[1]
dest=pathlib.Path(args[args.index('-o')+1])
dest.write_bytes(b'corrupted' if {case=='corrupt'!r} else source.read_bytes())
''')
                if case=='rollback':
                    (r/'fail-once').touch()
                    executable('mv',f'''import os,pathlib,sys
args=[a for a in sys.argv[1:] if a!='-f'];marker=pathlib.Path({str(r/'fail-once')!r})
if args[-1].endswith('/settings_052.js') and marker.exists():marker.unlink();sys.exit(1)
os.replace(*args)
''')
                env=dict(os.environ,FX_LUCI_FIX_ROOT=str(r),PATH=str(r/'bin')+':'+os.environ['PATH'])
                result=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode==0,case=='success',result.stdout+result.stderr)
                after={p.name:p.read_bytes() for p in (r/REL).iterdir()}
                if case=='success':
                    self.assertEqual(after,{n+'.js':(FILES/REL/(n+'.js')).read_bytes() for n in old})
                    self.assertEqual(len(list((r/'root').iterdir())),1)
                    requests=(r/'requests').read_text()
                    again=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True,timeout=20)
                    self.assertEqual(again.returncode,0,again.stderr)
                    self.assertEqual((r/'requests').read_text(),requests)
                    self.assertEqual(len(list((r/'root').iterdir())),1)
                else:self.assertEqual(after,before)
                if case in ('unknown','version'):
                    self.assertFalse((r/'requests').exists());self.assertFalse(list((r/'root').iterdir()))

if __name__=='__main__':unittest.main()
