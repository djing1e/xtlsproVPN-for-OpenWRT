import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
MOCK=r'''#!/usr/bin/env python3
import os,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT'])
if Path(sys.argv[0]).name=='ip': print((r/'routes').read_text())
else:
 key=sys.argv[-1]
 values={'xray_core.general.lab_iface':'br-lan','xray_lab_dns.main.enabled':os.environ.get('DNS','0'),'xray_lab_dns.main.sources':os.environ.get('SOURCES','')}
 print(values.get(key,''))
'''

class Redirects(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.r=Path(self.temp.name);self.sys=self.r/'sys';self.run=self.r/'run'
        for name in ('all','default','br-lan','wan','guest'):
            p=self.sys/name;p.mkdir(parents=True);(p/'send_redirects').write_text('1\n')
        (self.r/'routes').write_text('default via 172.16.100.1 dev br-lan proto static\n')
        tools=self.r/'tools';tools.mkdir()
        for name in ('ip','uci'):
            p=tools/name;p.write_text(MOCK);p.chmod(0o755)
        self.env={**os.environ,'TEST_ROOT':str(self.r),'PATH':str(tools)+':'+os.environ['PATH']}
        source=(ROOT/'usr/bin/xray-lab-redirects').read_text().replace('RUN=/var/run/xray-lab-control','RUN='+str(self.run)).replace('SYS=/proc/sys/net/ipv4/conf','SYS='+str(self.sys))
        self.helper=self.r/'helper';self.helper.write_text(source)

    def value(self,name):return (self.sys/name/'send_redirects').read_text().strip()
    def command(self,action,expected=0):
        p=subprocess.run(['sh',str(self.helper),action],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,expected,p.stderr)

    def test_one_arm_repeated_start_and_stop(self):
        self.command('up');self.command('up')
        self.assertEqual([self.value(x) for x in ('all','br-lan','wan','default')],['0','0','1','1'])
        self.command('down');self.command('down')
        self.assertEqual(self.value('all'),'1');self.assertEqual(self.value('br-lan'),'1')

    def test_separate_wan_does_not_change_settings(self):
        (self.r/'routes').write_text('default via 10.0.0.1 dev wan\n')
        self.command('up')
        self.assertTrue(all(self.value(x)=='1' for x in ('all','br-lan','wan','default')))

    def test_route_change_restores_old_interface(self):
        self.command('up')
        (self.r/'routes').write_text('default via 10.0.0.1 dev wan\n')
        self.command('up');self.assertEqual(self.value('all'),'1');self.assertEqual(self.value('br-lan'),'1')

    def test_original_zero_and_subsequent_admin_change(self):
        (self.sys/'all/send_redirects').write_text('0\n')
        self.command('up');(self.sys/'br-lan/send_redirects').write_text('1\n')
        self.command('down')
        self.assertEqual(self.value('all'),'0');self.assertEqual(self.value('br-lan'),'1')

    def test_custom_sources_and_multipath(self):
        self.env.update(DNS='1',SOURCES='guest br-lan')
        (self.r/'routes').write_text('default proto static\n nexthop via 10.0.0.1 dev guest weight 1\n nexthop via 172.16.100.1 dev br-lan weight 1\n')
        self.command('up');self.assertEqual(self.value('guest'),'0');self.assertEqual(self.value('br-lan'),'0')
        self.command('down');self.assertEqual(self.value('guest'),'1')

    def test_invalid_source_refused_before_changes(self):
        self.env.update(DNS='1',SOURCES='../all')
        self.command('up',1);self.assertEqual(self.value('all'),'1')

if __name__=='__main__':unittest.main()
