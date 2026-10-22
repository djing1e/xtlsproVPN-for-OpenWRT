import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'

@unittest.skipUnless(shutil.which('ucode'), 'ucode runtime required')
class DirectSubscription(unittest.TestCase):
    def test_download_is_direct_even_when_proxy_environment_or_fallback_is_set(self):
        source=(FILES/'usr/lib/forkop-xray/main.uc').read_text()
        function=source[source.index('function fetch(s)'):source.index('function summary()')]
        prelude="let fs=require('fs'),run_dir=ARGV[0];function quote(s){return chr(39)+replace(''+s,/'/g,chr(39)+chr(92)+chr(39)+chr(39))+chr(39);}function command(a){return join(' ',map(a,quote));}function accept(){print('accepted');}\n"
        for rc,http in [(0,'200'),(6,'000'),(7,'000'),(28,'000'),(35,'000'),(60,'000'),(22,'403')]:
            with self.subTest(rc=rc),tempfile.TemporaryDirectory() as temp:
                p=Path(temp)
                (p/'run.uc').write_text(prelude+function+"fetch({subscription_url:'https://private.test/sub/PRIVATE-TOKEN',user_agent:'Xray/test',hwid:'router-12345'});")
                (p/'curl').write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:];p=Path(os.environ['DIRECT_TEST_ROOT'])
with (p/'calls').open('a') as f:f.write(json.dumps(a)+'\\n')
(p/'headers').write_text(Path(a[a.index('--config')+1]).read_text())
print(os.environ['DIRECT_HTTP'],end='');sys.exit(int(os.environ['DIRECT_RC']))
''');(p/'curl').chmod(0o755)
                env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],DIRECT_TEST_ROOT=str(p),DIRECT_RC=str(rc),DIRECT_HTTP=http,
                         HTTPS_PROXY='socks5h://127.0.0.1:1080',ALL_PROXY='socks5h://127.0.0.1:11500',FX_FALLBACK_SOCKS='127.0.0.1:11500')
                r=subprocess.run(['ucode',str(p/'run.uc'),str(p)],env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(r.returncode==0,rc==0,r.stderr)
                calls=[json.loads(s) for s in (p/'calls').read_text().splitlines()];self.assertEqual(len(calls),1)
                a=calls[0];self.assertEqual(a[a.index('--noproxy')+1],'*');self.assertNotIn('--proxy',a)
                self.assertIn('--proto',a);self.assertIn('--proto-redir',a);self.assertIn('=https',a);self.assertNotIn('-k',a)
                self.assertNotIn('PRIVATE-TOKEN',r.stdout+r.stderr+' '.join(a))
                self.assertIn('X-HWID: router-12345',(p/'headers').read_text())
                self.assertFalse((p/'curl.conf').exists())
                if rc:self.assertIn('curl='+str(rc),r.stderr)

if __name__=='__main__':unittest.main()
