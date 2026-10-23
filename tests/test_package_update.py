"""Run release validation and the actual installer against an isolated router fixture."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
LIB=FILES/'usr/share/xray/lab'
REPO='https://github.com/djing1e/xtlsproVPN-for-OpenWRT'
VERSION='1.1.2-r1'
APK=b'isolated application package fixture'
DIGEST=hashlib.sha256(APK).hexdigest()

def fixture(platforms=('25.12.5','25.12.6')):
    name='xtlsprovpn-'+VERSION+'.apk'
    manifest={'schema':1,'tag':'v1.1.2','version':VERSION,'openwrt':list(platforms),
              'architectures':['aarch64'],'installed_size_kb':4096,
              'apk':{'name':name,'sha256':DIGEST,'size':len(APK)}}
    body=(json.dumps(manifest)+'\n').encode()
    release={'draft':False,'prerelease':False,'tag_name':'v1.1.2','assets':[
        {'name':name,'browser_download_url':REPO+'/releases/download/v1.1.2/'+name,
         'digest':'sha256:'+DIGEST,'size':len(APK)},
        {'name':'update.json','browser_download_url':REPO+'/releases/download/v1.1.2/update.json',
         'digest':'sha256:'+hashlib.sha256(body).hexdigest(),'size':len(body)}]}
    return release,manifest,body

MOCK=r'''#!/usr/bin/env python3
import json,os,re,shutil,subprocess,sys
from pathlib import Path
r=Path(os.environ['TEST_ROUTER']);mode=os.environ.get('TEST_MODE','ok');a=sys.argv[1:];cmd=Path(sys.argv[0]).name
with (r/'calls').open('a') as f:f.write(json.dumps([cmd]+a)+'\n')
if cmd=='uname':print(os.environ.get('TEST_ARCH','aarch64'))
elif cmd=='sync':pass
elif cmd=='sleep':pass
elif cmd=='pidof':sys.exit(1)
elif cmd=='df':print('Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture 100000 1000 '+('100' if mode=='no-flash' else '99000')+' 1% /overlay')
elif cmd=='curl':
 if mode=='network':sys.exit(22)
 url=a[a.index('-o')-1];target=Path(a[a.index('-o')+1])
 src='release.json' if url.endswith('/latest') else 'update.json' if url.endswith('/update.json') else 'package.apk'
 target.write_bytes((r/src).read_bytes())
 if mode=='corrupt' and src=='package.apk':target.write_bytes(b'tampered')
elif cmd=='jsonfilter':
 d=json.loads(Path(a[a.index('-i')+1]).read_text());q=a[a.index('-e')+1]
 try:
  for k in q.removeprefix('@.').split('.'):d=d[k]
 except (KeyError,TypeError):sys.exit(1)
 print(str(d).lower() if isinstance(d,bool) else d)
elif cmd=='apk':
 v=(r/'installed').read_text().strip()
 def ver(x):return tuple(map(int,re.split(r'\.|-r',x)))
 if a[:2]==['info','-v']:
  print('xtlsprovpn-'+v if '-e' in a else 'xtlsprovpn-'+v+' description:\nRouter administration\n')
 elif a[:2]==['info','-e']:
  c=a[2]
  if '>=' in c:sys.exit(0 if ver(v)>=ver(c.split('>=')[1]) else 1)
  elif '=' in c:sys.exit(0 if v==c.split('=')[1] else 1)
  else:sys.exit(0 if c=='xtlsprovpn' else 1)
 elif a[0]=='add':
  if mode=='apk-failure':sys.exit(4)
  assert '--allow-untrusted' in a
  (r/'installed').write_text('1.1.2-r1')
  # Simulate replacing the on-disk controller and launcher during upgrade.
  (r/'usr/share/xray/lab/package_update.uc').write_text('die("replaced on disk");')
  (r/'usr/bin/xray-lab-package').write_text('exit 99')
 else:raise RuntimeError(a)
elif cmd=='uci':
 print('0' if mode=='paused' else '1')
elif cmd=='ucode':
 script=a[0]
 if script.endswith('/control.uc'):print(json.dumps({'proxy_ok':mode!='health-failure'}))
 elif script.endswith('/dns_query.uc'):print('{"ok":true}')
 else:
  env=dict(os.environ);env['LD_LIBRARY_PATH']=os.environ.get('REAL_UCODE_LIB','')
  sys.exit(subprocess.call([os.environ['REAL_UCODE']]+a,env=env))
else:raise RuntimeError(cmd)
'''

@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class PackageUpdate(unittest.TestCase):
    def run_model(self,release,manifest,platform='25.12.5',arch='aarch64'):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'r.json').write_text(json.dumps(release));(d/'m.json').write_text(json.dumps(manifest))
            p=subprocess.run(['ucode',str(LIB/'package_update.uc'),'plan',str(d/'r.json'),str(d/'m.json'),
                              str(d/'plan.json'),platform,arch],capture_output=True,text=True)
            return p,json.loads((d/'plan.json').read_text()) if p.returncode==0 else None

    def test_compatible_release_and_manifest(self):
        r,m,_=fixture();p,plan=self.run_model(r,m)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(plan['version'],VERSION);self.assertEqual(plan['sha256'],DIGEST)

    def test_rejects_untrusted_or_ambiguous_metadata(self):
        for case in ['prerelease','draft','foreign-url','mismatch','duplicate','no-manifest','wrong-tag','wrong-platform','traversal','oversize','bad-arch']:
            with self.subTest(case=case):
                r,m,_=fixture();platform='25.12.5';arch='aarch64'
                if case in ('draft','prerelease'):r[case]=True
                elif case=='foreign-url':r['assets'][0]['browser_download_url']='https://example.com/p.apk'
                elif case=='mismatch':m['apk']['sha256']='a'*64
                elif case=='duplicate':r['assets'].append(copy.deepcopy(r['assets'][0]))
                elif case=='no-manifest':r['assets'].pop()
                elif case=='wrong-tag':m['tag']='v9.0.0'
                elif case=='wrong-platform':platform='24.10.0'
                elif case=='traversal':m['apk']['name']='../../package.apk'
                elif case=='oversize':m['apk']['size']=9000000
                elif case=='bad-arch':arch='mips'
                p,_=self.run_model(r,m,platform,arch);self.assertNotEqual(p.returncode,0)

    def run_worker(self,mode='ok',action='install',expected=VERSION,digest=DIGEST,
                   platform='25.12.5',arch='aarch64',platforms=('25.12.5','25.12.6')):
        with tempfile.TemporaryDirectory(prefix='xtls-package.fixture.') as temp:
            r=Path(temp);work=r/'xtls-package.work';work.mkdir();bindir=r/'bin';bindir.mkdir()
            paths=['var/run/xtlspro-package','var/run/xray-lab-control','var/run/xtlspro-netbird',
                   'etc/config','etc/forkop-xray','etc/netbird','usr/bin','usr/share/xray/lab','usr/libexec/forkop-xray','overlay']
            for path in paths:(r/path).mkdir(parents=True,exist_ok=True)
            (r/'etc/openwrt_release').write_text("DISTRIB_RELEASE='"+platform+"'\n")
            (r/'meminfo').write_text('MemAvailable: '+('12000' if mode=='no-ram' else '48000')+' kB\n')
            (r/'etc/config/xray_core').write_text('private router configuration')
            (r/'etc/forkop-xray/subscription.json').write_text('private subscription')
            (r/'etc/netbird/config.json').write_text('private peer identity')
            (r/'usr/libexec/forkop-xray/xray').write_text('unchanged original core')
            (r/'usr/bin/xray-lab-netbird').write_text('#!/bin/sh\necho \'{"connected":true}\'\n')
            (r/'usr/bin/xray-lab-netbird').chmod(0o755)
            (r/'usr/bin/xray-lab-control').write_text('#!/bin/sh\necho \'{"interception":{"active":true}}\'\n')
            (r/'usr/bin/xray-lab-control').chmod(0o755)
            release,manifest,body=fixture(platforms)
            if mode in ('same','newer','no-manifest'):
                if mode=='no-manifest':release['assets'].pop()
            (r/'installed').write_text('1.1.2-r1' if mode=='same' else '1.2.0-r1' if mode=='newer' else '1.1.1-r1')
            (r/'release.json').write_text(json.dumps(release));(r/'update.json').write_bytes(body);(r/'package.apk').write_bytes(APK)
            (r/'calls').touch()
            def patch(s):
                # Redirect every router-owned absolute path, never host system files.
                for path in ['/var/run/xtlspro-package','/var/run/xray-lab-control','/var/run/xtlspro-netbird',
                             '/etc/xtlspro-update','/etc/openwrt_release','/etc/config','/usr/bin/xray-lab-package',
                             '/usr/bin/xray-lab-netbird','/usr/bin/xray-lab-control','/usr/share/xray/lab',
                             '/usr/libexec/forkop-xray/xray','/overlay']:
                    s=s.replace(path,str(r/path.lstrip('/')))
                return s.replace('/proc/meminfo',str(r/'meminfo')).replace('tar -C / -czf','tar -C '+str(r)+' -czf').replace('[ ! -d "/$path" ]','[ ! -d "'+str(r)+'/$path" ]')
            worker=patch((FILES/'usr/bin/xray-lab-package').read_text())
            (work/'worker').write_text(worker)
            for name in ['package_update.uc','package_release.mjs']:
                content=patch((LIB/name).read_text());(work/name).write_text(content)
                (r/'usr/share/xray/lab'/name).write_text(content)
            (r/'usr/bin/xray-lab-package').write_text(worker)
            for name in ('curl','apk','jsonfilter','df','uname','uci','pidof','ucode','sync','sleep'):
                p=bindir/name;p.write_text(MOCK);p.chmod(0o755)
            env=dict(os.environ,TEST_ROUTER=str(r),TEST_MODE=mode,TEST_ARCH=arch,PATH=str(bindir)+':'+os.environ['PATH'],
                     REAL_UCODE=shutil.which('ucode'),REAL_UCODE_LIB=os.environ.get('LD_LIBRARY_PATH',''))
            lock=None
            if mode=='busy':
                import fcntl
                lock=(r/'var/run/xray-lab-control/action.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            p=subprocess.run(['sh',str(work/'worker'),'worker',action,expected,digest],env=env,capture_output=True,text=True,timeout=15)
            if lock:lock.close()
            job=json.loads((r/'var/run/xtlspro-package/job.json').read_text())
            calls=[json.loads(x) for x in (r/'calls').read_text().splitlines()]
            backup=(r/'etc/xtlspro-update/backup.tar.gz').exists()
            if backup:
                import tarfile
                with tarfile.open(r/'etc/xtlspro-update/backup.tar.gz') as t:
                    self.assertIn('etc/netbird/config.json',t.getnames())
                    self.assertEqual(t.extractfile('etc/netbird/config.json').read(),b'private peer identity')
            log=(r/'var/run/xtlspro-package/worker.log').read_text()
            self.assertFalse(work.exists(),'RAM worker/staging not removed')
            self.assertNotIn('private peer identity',json.dumps(job))
            self.assertEqual((r/'usr/libexec/forkop-xray/xray').read_text(),'unchanged original core')
            return p,job,calls,backup,log

    def test_install_survives_replaced_files_and_verifies_services(self):
        p,j,c,b,log=self.run_worker()
        self.assertEqual(p.returncode,0,log);self.assertEqual(j['state'],'done');self.assertTrue(b)
        self.assertTrue(any(x[0]=='apk' and x[1]=='add' for x in c))
        self.assertEqual(sum(x[0]=='ucode' and '/dns_query.uc' in x[1] for x in c),2)

    def test_openwrt_25126_check_and_install_use_the_real_worker(self):
        for action in ('check','install'):
            with self.subTest(action=action):
                p,j,c,b,log=self.run_worker(action=action,platform='25.12.6')
                self.assertEqual(p.returncode,0,log);self.assertEqual(j['state'],'done')
                self.assertEqual(any(x[0]=='apk' and x[1]=='add' for x in c),action=='install')
                self.assertEqual(b,action=='install')

    def test_unsupported_firmware_and_architecture_fail_before_download(self):
        for platform,arch in [('25.12.7','aarch64'),('SNAPSHOT','aarch64'),('25.12.6','mips')]:
            with self.subTest(platform=platform,arch=arch):
                p,j,c,b,log=self.run_worker(platform=platform,arch=arch)
                self.assertNotEqual(p.returncode,0,log);self.assertEqual(j['state'],'failed')
                self.assertFalse(any(x[0] in ('apk','curl') for x in c));self.assertFalse(b)

    def test_25126_still_requires_permission_in_the_verified_manifest(self):
        p,j,c,b,log=self.run_worker(platform='25.12.6',platforms=('25.12.5',))
        self.assertNotEqual(p.returncode,0,log)
        self.assertFalse(any(x[0]=='apk' and x[1]=='add' for x in c));self.assertFalse(b)

    def test_paused_proxy_stays_paused(self):
        p,j,c,_,log=self.run_worker('paused');self.assertEqual(p.returncode,0,log)
        self.assertFalse(any(x[0]=='ucode' and '/control.uc' in x[1] for x in c))

    def test_preflight_failure_never_installs(self):
        for mode in ['network','corrupt','no-ram','no-flash','same','newer','busy','no-manifest']:
            with self.subTest(mode=mode):
                p,j,c,b,log=self.run_worker(mode)
                self.assertNotEqual(p.returncode,0,log);self.assertEqual(j['state'],'failed')
                self.assertFalse(any(x[0]=='apk' and x[1]=='add' for x in c));self.assertFalse(b)

    def test_changed_release_requires_fresh_confirmation(self):
        p,j,c,_,log=self.run_worker(expected='1.1.1-r2')
        self.assertNotEqual(p.returncode,0,log)
        self.assertFalse(any(x[0]=='apk' and x[1]=='add' for x in c))

    def test_postinstall_failure_is_honest_and_keeps_backup(self):
        for mode in ['apk-failure','health-failure']:
            with self.subTest(mode=mode):
                p,j,_,b,log=self.run_worker(mode)
                self.assertNotEqual(p.returncode,0,log);self.assertTrue(b)
                self.assertIn('Автоматический откат',j['message'])

    def test_check_does_not_install_or_backup(self):
        for mode in ['ok','same','newer']:
            p,j,c,b,log=self.run_worker(mode,action='check')
            self.assertEqual(p.returncode,0,log);self.assertEqual(j['state'],'done');self.assertFalse(b)
            self.assertFalse(any(x[0]=='apk' and x[1]=='add' for x in c))

    def test_manifest_generator_binds_exact_artifact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);apk=d/('xtlsprovpn-'+VERSION+'.apk');apk.write_bytes(APK)
            p=subprocess.run(['python3',str(ROOT/'scripts/make-update-manifest.py'),str(apk),'--output',str(d/'update.json')],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            m=json.loads((d/'update.json').read_text());r,_,_=fixture()
            result,plan=self.run_model(r,m)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(plan['sha256'],DIGEST)

    def test_launcher_registers_private_worker_with_procd(self):
        with tempfile.TemporaryDirectory(prefix='xtls-launch.') as temp:
            d=Path(temp);bindir=d/'bin';bindir.mkdir();lib=d/'lib';lib.mkdir()
            for name in ['package_update.uc','package_release.mjs']:(lib/name).write_text((LIB/name).read_text())
            script=d/'launcher'
            script.write_text((FILES/'usr/bin/xray-lab-package').read_text()
                              .replace('/var/run/xtlspro-package',str(d/'run'))
                              .replace('/usr/share/xray/lab',str(lib))
                              .replace('/usr/bin/xray-lab-package',str(script))
                              .replace('/tmp/xtls-package.',str(d/'xtls-package.')))
            stub='''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
d=Path(os.environ['LAUNCH_ROOT']);cmd=Path(sys.argv[0]).name
if cmd=='ubus':
 if sys.argv[3]=='list':print('{}')
 else:(d/'service.json').write_text(sys.argv[4])
elif cmd=='jsonfilter':sys.exit(1)
elif cmd=='ucode':pass
'''
            for name in ['ubus','jsonfilter','ucode']:
                p=bindir/name;p.write_text(stub);p.chmod(0o755)
            env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'],LAUNCH_ROOT=str(d))
            p=subprocess.run(['sh',str(script),'launch','install',VERSION,DIGEST],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertTrue(json.loads(p.stdout)['ok'])
            service=json.loads((d/'service.json').read_text());self.assertEqual(service['name'],'xtls_package_update')
            worker=service['instances']['worker'];self.assertEqual(worker['command'][0],'/bin/sh')
            copied=Path(worker['command'][1]);self.assertTrue(copied.exists())
            self.assertNotEqual(copied,script)
            self.assertTrue((copied.parent/'package_update.uc').exists())
            self.assertTrue((copied.parent/'package_release.mjs').exists())
            self.assertNotIn('respawn',worker)
            self.assertEqual(copied.parent.stat().st_mode & 0o777,0o700)

    def test_rpc_rejects_injection_before_launch(self):
        for request in [{'action':'install','version':"1.1.2-r1';reboot",'sha256':DIGEST},
                        {'action':'install','version':VERSION,'sha256':'$(reboot)'},
                        {'action':'exec','version':VERSION,'sha256':DIGEST}]:
            p=subprocess.run(['ucode',str(FILES/'usr/libexec/rpcd/xray_lab_package'),'call','launch'],
                             input=json.dumps(request),capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn('error',json.loads(p.stdout))

    def test_status_recognizes_interrupted_previous_boot(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);state=d/'state';state.mkdir();run=d/'run';run.mkdir();bindir=d/'bin';bindir.mkdir()
            (bindir/'apk').write_text('#!/bin/sh\ncase "$*" in\n"info -v -e xtlsprovpn") echo xtlsprovpn-1.1.1-r1 ;;\n*) printf "xtlsprovpn-1.1.1-r1 description:\\nRouter administration\\n" ;;\nesac\n');(bindir/'apk').chmod(0o755)
            s=(LIB/'package_update.uc').read_text().replace('/var/run/xtlspro-package',str(run)).replace('/etc/xtlspro-update',str(state))
            (d/'package_update.uc').write_text(s);shutil.copy2(LIB/'package_release.mjs',d)
            (state/'last.json').write_text(json.dumps({'state':'running','boot':'previous-boot','pid':1,'action':'install','version':VERSION}))
            p=subprocess.run(['ucode',str(d/'package_update.uc'),'status'],env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH']),capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr);j=json.loads(p.stdout)
            self.assertEqual(j['job']['state'],'interrupted');self.assertEqual(j['installed'],'1.1.1-r1')

if __name__=='__main__':unittest.main()
