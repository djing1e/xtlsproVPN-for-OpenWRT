import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'package/xtlsprovpn/files/usr/share/xray/lab/dns_forward.uc'
MOCK = '''import * as fs from 'fs';
export function cursor(dir) {
    let path=dir+'/dhcp.json',data=json(fs.readfile(path));
    return {
        load:function(){return true;},
        get_all:function(config,name){return name?data[name]:data;},
        set:function(config,name,key,value){data[name][key]=value;return true;},
        delete:function(config,name,key){delete data[name][key];return true;},
        commit:function(){if(getenv('FAIL_COMMIT'))return false;return fs.writefile(path,sprintf('%J',data))!=null;}
    };
};
'''


@unittest.skipUnless(shutil.which('ucode'), 'ucode runtime required')
class DNSForward(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'uci.uc').write_text(MOCK)
        self.path=self.root/'dhcp.json';self.state=self.root/'state.json'
        self.original={'main':{'.type':'dnsmasq','cachesize':'1000','noresolv':'1',
            'server':['1.1.1.1','8.8.8.8','/#/9.9.9.9','/mtrx.win/127.0.0.153','/lan/']},
            'second':{'.type':'dnsmasq','server':'46.61.250.136'},
            'lan':{'.type':'dhcp','ignore':'0'}}
        self.write(self.original)

    def write(self,data):self.path.write_text(json.dumps(data))
    def read(self):return json.loads(self.path.read_text())
    def run_op(self,*args,fail=False):
        env=dict(os.environ,FX_DNS_DHCP_DIR=str(self.root),FX_DNS_FORWARD_STATE=str(self.state))
        if fail:env['FAIL_COMMIT']='1'
        p=subprocess.run(['ucode','-L',str(self.root),str(SCRIPT),*args],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode==0,not fail,p.stderr)

    def test_remove_competing_defaults_preserve_domains_and_restore_exactly(self):
        self.run_op('up')
        data=self.read()
        self.assertEqual(data['main']['server'],['/mtrx.win/127.0.0.153','/lan/'])
        self.assertNotIn('server',data['second']);self.assertEqual(data['second']['noresolv'],'1')
        self.assertEqual(data['main']['cachesize'],'1000')
        self.assertEqual(self.state.stat().st_mode&0o777,0o600)
        self.run_op('up');self.run_op('down');self.run_op('down')
        self.assertEqual(self.read(),self.original);self.assertFalse(self.state.exists())

    def test_restore_does_not_overwrite_administrator_edits(self):
        self.run_op('up');data=self.read()
        data['main']['server']=['/new.internal/10.0.0.1'];data['second']['noresolv']='0'
        data['lan']['ignore']='1';self.write(data)
        self.run_op('down');data=self.read()
        self.assertEqual(data['main']['server'],['/new.internal/10.0.0.1'])
        self.assertEqual(data['second']['noresolv'],'0');self.assertEqual(data['lan']['ignore'],'1')

    def test_per_instance_does_not_touch_other_dnsmasq(self):
        self.run_op('up','main')
        self.assertEqual(self.read()['second'],self.original['second'])
        self.run_op('down');self.assertEqual(self.read(),self.original)

    def test_failed_commit_leaves_recovery_and_original_configuration(self):
        self.run_op('up',fail=True)
        self.assertTrue(self.state.exists());self.assertEqual(self.read(),self.original)
        self.run_op('down');self.assertEqual(self.read(),self.original)

    def test_reapply_captures_later_user_changes_for_subsequent_stop(self):
        self.run_op('up');data=self.read();data['main']['server']=['9.9.9.9','/new/10.0.0.1'];self.write(data)
        self.run_op('up');self.assertEqual(self.read()['main']['server'],['/new/10.0.0.1'])
        self.run_op('down');self.assertEqual(self.read()['main']['server'],['9.9.9.9','/new/10.0.0.1'])


if __name__=='__main__':unittest.main()
