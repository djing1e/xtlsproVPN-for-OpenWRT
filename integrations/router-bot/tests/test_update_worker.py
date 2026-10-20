import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import test_admin_worker as fixtures

BASE = Path(__file__).resolve().parents[1] / 'router'
REQUEST = '11111111-2222-4333-8444-555555555555'
PLAN = '11111111-2222-4333-8444-555555555556'


@unittest.skipUnless(shutil.which('ucode'), 'host ucode required')
class UpdateWorkerTests(unittest.TestCase):
    make = fixtures.AdminWorkerTests.make

    def setUp(self):
        fixtures.AdminWorkerTests.setUp(self)
        self.versions = self.root / 'versions.json'
        self.initial = {'app':'1.3.0-r4','xray':'26.7.28','netbird':'0.78.1-r1'}
        self.versions.write_text(json.dumps(self.initial))
        self.calls = self.root / 'native-calls'
        for directory in ('xtlspro-package','xtlspro-netbird','xray-lab-control'):
            (self.run / directory).mkdir(exist_ok=True)
        self.etc = self.root / 'etc'
        (self.etc / 'config').mkdir(parents=True)
        (self.etc / 'dropbear').mkdir()
        (self.etc / 'config/network').write_text('PRESERVED')
        self.make(self.bins / 'apk', '''exec python3 - "$@" <<'END'
import json,sys
v=json.load(open(''' + repr(str(self.versions)) + '''))
if sys.argv[1]=='info':
 c='app' if sys.argv[-1]=='xtlsprovpn' else 'netbird'
 print(('xtlsprovpn-' if c=='app' else 'netbird-')+v[c])
elif sys.argv[1]=='version':print('<' if sys.argv[-2]!=sys.argv[-1] else '=')
else:sys.exit(1)
END''')
        self.make(self.bins / 'xray', "python3 -c \"import json;print('Xray '+json.load(open('"+str(self.versions)+"'))['xray'])\"")
        self.native_uc = self.root / 'netbird.uc'
        self.native_uc.write_text("// FX_NETBIRD_EXPECTED_VERSION\n")
        driver = '''#!/usr/bin/env python3
import json,os,sys,time
from pathlib import Path
root=Path(''' + repr(str(self.root)) + ''');run=root/'run';versions=root/'versions.json'
v=json.loads(versions.read_text());a=sys.argv[1:];component={'xray-lab-core':'xray','xray-lab-package':'app','xray-lab-netbird':'netbird'}[Path(sys.argv[0]).name]
if component=='xray' and os.environ.get('FX_CORE_ALLOW_PRERELEASE')!='0':sys.exit(3)
target={'app':'1.3.1-r1','xray':'26.10.12','netbird':'0.79.0-r1'}[component]
with (root/'native-calls').open('a') as f:f.write(json.dumps([component,*a])+'\\n')
action=a[0] if component=='xray' else a[1]
check=action in ('list','check','check_update')
if component=='xray':
 catalog={'checked':int(time.time()),'releases':[{'version':target,'prerelease':False}]};path=run/'xray-lab-control/core-releases.json'
elif component=='app':
 catalog={'checked':int(time.time()),'version':target,'sha256':'a'*64};path=run/'xtlspro-package/catalog.json'
else:
 catalog={'checked':int(time.time()),'installed':v[component],'available':target,'update_available':v[component]!=target};path=run/'xtlspro-netbird/catalog.json'
path.write_text(json.dumps(catalog))
if not check:
 if component=='app' and a[2:]!=[target,'a'*64]:sys.exit(1)
 if component=='xray' and a[1:]!=[target]:sys.exit(1)
 if component=='netbird' and os.environ.get('FX_NETBIRD_EXPECTED_VERSION')!=target:sys.exit(1)
 v[component]=target;versions.write_text(json.dumps(v))
if component!='xray':
 (path.parent/'job.json').write_text(json.dumps({'action':action,'state':'done','updated':int(time.time())}))
 print('{"ok":true}')
'''
        for name in ('xray-lab-package','xray-lab-core','xray-lab-netbird'):
            p=self.bins/name;p.write_text(driver);p.chmod(0o700)
        health = self.root / 'health.uc'
        health.write_text("print('{\"proxy_ok\":true}');")
        self.uc = self.root / 'updates.uc'
        self.worker = self.root / 'update-worker'
        replacements={
            '/var/run':str(self.run),'/etc/xtlspro-bot/updates.uc':str(self.uc),
            '/proc/sys/kernel/random/boot_id':str(self.boot),'/proc/uptime':str(self.uptime),
            '/usr/libexec/forkop-xray/xray':str(self.bins/'xray'),
            '/usr/bin/netbird':str(self.bins/'netbird'),
            '/root/.ssh/known_hosts':str(self.root/'known_hosts'),
            '/usr/share/xray/lab/netbird.uc':str(self.native_uc),
            '/usr/share/xray/lab/control.uc':str(health),
            '/usr/share/xray/lab/dns_query.uc':str(health),
            '/root/xtls-before-bot-update.':str(self.root/'backup.'),
            '/etc/config':str(self.etc/'config'),'/etc/dropbear':str(self.etc/'dropbear'),
            '/etc/xtlspro-rescue':str(self.etc/'xtlspro-rescue'),
        }
        for source,dest in [('updates.uc',self.uc),('update-worker',self.worker)]:
            text=(BASE/source).read_text()
            for a,b in replacements.items():text=text.replace(a,b)
            text=text.replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin','PATH='+str(self.bins)+':'+os.environ['PATH'])
            text=text.replace('tar -C / ', 'tar -C '+str(self.root)+' ')
            text=text.replace('"/$path"','"'+str(self.root)+'/$path"')
            dest.write_text(text);dest.chmod(0o700)

    def call(self,*args):
        result=subprocess.run([str(self.worker),*args],env=self.env,capture_output=True,text=True,timeout=10)
        return result,json.loads(result.stdout) if result.stdout else None

    def wait_job(self):
        for _ in range(1500):
            p=self.run/'xtlspro-bot-updates/job.json'
            if p.exists():
                j=json.loads(p.read_text())
                if j['state'] in ('done','failed'):return j
            time.sleep(.02)
        self.fail('Update worker timeout')

    def test_each_check_leaves_versions_unchanged(self):
        for n,component in enumerate(('app','xray','netbird')):
            request=REQUEST[:-1]+str(n+1)
            result,receipt=self.call('launch','check',component,request,request)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertTrue(receipt['accepted'])
            job=self.wait_job()
            self.assertEqual(job['state'],'done',(self.run/'xtlspro-bot-updates/job.log').read_text())
        self.assertEqual(json.loads(self.versions.read_text()),self.initial)
        self.assertFalse(list(self.root.glob('backup.*')))

    def test_each_install_uses_exact_plan_and_preserves_settings(self):
        for n,component in enumerate(('app','xray','netbird')):
            check=REQUEST[:-1]+str(n+1)
            install=PLAN[:-2]+'9'+str(n+1)
            self.call('launch','check',component,check,check)
            self.assertEqual(self.wait_job()['state'],'done')
            result,receipt=self.call('launch','install',component,install,check)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertEqual(self.wait_job()['state'],'done',(self.run/'xtlspro-bot-updates/job.log').read_text())
            self.uptime.write_text(str(1400+n*400)+'.00 0\n')
        self.assertEqual((self.etc/'config/network').read_text(),'PRESERVED')
        self.assertEqual(json.loads(self.versions.read_text()),{'app':'1.3.1-r1','xray':'26.10.12','netbird':'0.79.0-r1'})
        self.assertEqual(len(list(self.root.glob('backup.*'))),3)

    def test_install_without_matching_plan_never_calls_native_installer(self):
        result,data=self.call('launch','install','app',REQUEST,PLAN)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(data['error'],'plan_expired')
        self.assertFalse(self.calls.exists())

    def test_native_netbird_install_requires_version_binding_hook(self):
        self.call('launch','check','netbird',PLAN,PLAN)
        self.assertEqual(self.wait_job()['state'],'done')
        self.native_uc.write_text('// no binding hook')
        self.call('launch','install','netbird',REQUEST,PLAN)
        self.assertEqual(self.wait_job()['state'],'failed')
        self.assertEqual(json.loads(self.versions.read_text()),self.initial)
