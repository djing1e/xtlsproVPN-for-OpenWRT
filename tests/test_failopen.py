import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
LIB=FILES/'usr/share/xray/lab'

@unittest.skipUnless(shutil.which('ucode'),'host ucode required')
class FailOpenPolicy(unittest.TestCase):
    def decide(self,old=None,**patch):
        sample=dict(now=100,enabled=True,desired=True,interface_up=True,signature='wan1',settle=2,
                    busy=False,bypass=False,core=True,interception=True,probe_new=True,proxy_ok=False,direct_ok=False)
        sample.update(patch)
        code="import {decide} from '"+str(LIB/'watchdog.uc')+"';printf('%J',decide("+json.dumps(old or {})+","+json.dumps(sample)+"));"
        return json.loads(subprocess.check_output(['ucode','-e',code],text=True))
    def test_all_locations_dead_opens_even_if_direct_dns_also_fails(self):
        for direct in (False,True):
            state={}
            for n in range(3):
                r=self.decide(state,now=100+n*15,direct_ok=direct);state=r['state']
                self.assertEqual(r['action'],'bypass' if n==2 else None)
            self.assertEqual(r['reason'],'proxy_failed')
    def test_restart_limit_never_prevents_safety_bypass(self):
        r=self.decide({'failures':2,'restarts':[90,91,92],'last_restart':99})
        self.assertEqual(r['action'],'bypass')
    def test_one_failure_or_cached_sample_does_not_open(self):
        r=self.decide();self.assertIsNone(r['action'])
        r=self.decide(r['state'],probe_new=False,now=115)
        self.assertEqual(r['state']['failures'],1);self.assertIsNone(r['action'])
        r=self.decide(r['state'],proxy_ok=True)
        self.assertEqual(r['state']['failures'],0)
    def test_bypass_waits_for_two_fresh_successes(self):
        s={}
        for ok,expected in [(True,None),(False,None),(True,None),(True,'restore')]:
            r=self.decide(s,bypass=True,interception=False,proxy_ok=ok);s=r['state']
            self.assertEqual(r['action'],expected)
        r=self.decide(s,bypass=True,interception=False,proxy_ok=True,now=115)
        r=self.decide(r['state'],bypass=True,interception=False,proxy_ok=True,now=130)
        self.assertIsNone(r['action']) # Bound failed DNS/resume retries to once a minute.
    def test_intentional_stop_or_disabled_monitor_never_revives(self):
        for patch in ({'desired':False},{'enabled':False},{'busy':True}):
            r=self.decide({'failures':9,'successes':9},bypass=True,interception=False,proxy_ok=True,**patch)
            self.assertIsNone(r['action'])
    def test_incomplete_cleanup_is_retried_before_recovery(self):
        r=self.decide({'restarts':[90,91,92]},bypass=True,interception=False,cleanup_needed=True,proxy_ok=True)
        self.assertEqual(r['action'],'bypass')
    def test_dead_core_opens_then_restarts_only_in_direct_mode(self):
        s={}
        for n in range(3):r=self.decide(s,core=False,now=100+n*15);s=r['state']
        self.assertEqual(r['action'],'bypass')
        r=self.decide(s,bypass=True,interception=False,core=False,now=150)
        self.assertEqual(r['action'],'restart')
        r=self.decide(r['state'],bypass=True,interception=False,core=False,now=165)
        self.assertIsNone(r['action'])
    def test_uplink_change_opens_before_restarting(self):
        r=self.decide({'signature':'old'},now=100);self.assertEqual(r['reason'],'settling')
        r=self.decide(r['state'],now=103);self.assertEqual(r['action'],'bypass')
        r=self.decide(r['state'],bypass=True,interception=False,now=118)
        self.assertEqual(r['action'],'restart')
    def test_recovery_counter_only_after_interception_resumes(self):
        r=self.decide({'outage_start':1},bypass=True,interception=False,proxy_ok=True)
        self.assertNotIn('recoveries',r['state'])
        r=self.decide(r['state'],proxy_ok=True)
        self.assertEqual(r['state']['recoveries'],1)

class FailOpenInit(unittest.TestCase):
    def run_case(self,body):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);marker=d/'direct-mode';calls=d/'calls'
            src=(FILES/'etc/init.d/xray_core').read_text().replace('/var/run/xray-lab-control',str(d))
            pre='\nlogger(){ :; }; uci_get_by_type(){ echo 1; }; uci(){ echo 1; };\n'
            pre+='flush_dnsmasq(){ echo dns >> "'+str(calls)+'"; [ -f "'+str(marker)+'" ]; };\n'
            pre+='flush_firewall(){ echo firewall >> "'+str(calls)+'"; [ -f "'+str(marker)+'" ]; };\n'
            pre+='setup_dnsmasq(){ echo enable_dns >> "'+str(calls)+'"; };setup_firewall(){ echo enable_firewall >> "'+str(calls)+'"; };\n'
            p=d/'run';p.write_text(src+pre+body)
            r=subprocess.run(['sh',str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr+r.stdout)
            return marker.exists(),(d/'direct-mode.ready').exists(),calls.read_text() if calls.exists() else ''
    def test_suspend_marks_before_restoring_dns_and_firewall(self):
        marker,ready,calls=self.run_case('suspend_proxy\n')
        self.assertTrue(marker and ready);self.assertEqual(calls,'dns\nfirewall\n')
    def test_reload_cannot_reenable_interception_during_outage(self):
        _,_,calls=self.run_case('suspend_proxy;create_when_enable\n')
        self.assertEqual(calls,'dns\nfirewall\n')
    def test_partial_cleanup_keeps_retry_marker_and_runs_both_cleanups(self):
        marker,ready,calls=self.run_case('flush_dnsmasq(){ echo dns >> "'+str('/dev/null')+'";return 1; };suspend_proxy && exit 9;exit 0\n')
        self.assertTrue(marker);self.assertFalse(ready);self.assertEqual(calls,'firewall\n')

class FailOpenWorker(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run=self.root/'run';self.run.mkdir();self.bins=self.root/'bin';self.bins.mkdir()
        self.marker=self.run/'direct-mode';self.marker.touch();self.active=self.root/'interception';self.active.write_text('off')
        self.health=self.root/'healthy';self.health.write_text('true')
        self.dns=self.root/'dns';self.dns.write_text('ok');self.desired=self.root/'desired';self.desired.write_text('1')
        self.calls=self.root/'calls'
        def make(name,body):
            p=self.bins/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755);return p
        self.make=make
        make('uci','cat "'+str(self.desired)+'"')
        make('jsonfilter','cat >/dev/null; cat "'+str(self.health)+'"')
        make('ucode', '''case "$2" in
health) printf '{"proxy_ok":%s}\\n' "$(cat "'''+str(self.health)+'''")";;
jobset) echo "$3" >> "'''+str(self.calls)+'''";;
5300) echo "$4" >> "'''+str(self.calls)+'''";[ "$(cat "'''+str(self.dns)+'''")" != "$4" ];;
esac''')
        init=make('xray_core','''echo "$1" >> "'''+str(self.calls)+'''"
case "$1" in
suspend_proxy) touch "'''+str(self.marker)+'''";echo off > "'''+str(self.active)+'''";;
resume_proxy) rm -f "'''+str(self.marker)+'''";echo on > "'''+str(self.active)+'''";;
esac''')
        s=(FILES/'usr/bin/xray-lab-control').read_text().replace('/var/run/xray-lab-control',str(self.run)).replace('/etc/init.d/xray_core',str(init))
        self.script=self.root/'control';self.script.write_text(s);self.script.chmod(0o755)
        self.env=dict(os.environ,PATH=str(self.bins)+':'+os.environ['PATH'])
    def run_op(self,action):return subprocess.run([str(self.script),'worker',action,''],env=self.env,capture_output=True,text=True)
    def test_healthy_https_and_both_native_dns_protocols_required(self):
        r=self.run_op('restore');self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(self.marker.exists());self.assertEqual(self.active.read_text().strip(),'on')
        self.assertIn('udp\ntcp\nresume_proxy',self.calls.read_text())
    def test_failed_dns_or_https_keeps_direct_mode(self):
        for failure in ('udp','tcp','https'):
            with self.subTest(failure=failure):
                self.health.write_text('false' if failure=='https' else 'true');self.dns.write_text(failure)
                r=self.run_op('restore');self.assertNotEqual(r.returncode,0)
                self.assertTrue(self.marker.exists());self.assertEqual(self.active.read_text(),'off')
                self.assertNotIn('resume_proxy',self.calls.read_text())
    def test_manual_stop_wins_over_queued_automatic_restore(self):
        self.desired.write_text('0');r=self.run_op('restore')
        self.assertEqual(r.returncode,0);self.assertNotIn('resume_proxy',self.calls.read_text())
    def test_post_activation_https_failure_suspends_again(self):
        self.make('jsonfilter','cat >/dev/null; if [ -f "'+str(self.marker)+'" ];then echo true;else echo false;fi')
        r=self.run_op('restore');self.assertNotEqual(r.returncode,0)
        self.assertTrue(self.marker.exists());self.assertEqual(self.active.read_text().strip(),'off')
        self.assertIn('resume_proxy\nsuspend_proxy',self.calls.read_text())
    def test_bypass_does_not_stop_xray_or_change_desired_settings(self):
        r=self.run_op('bypass');self.assertEqual(r.returncode,0)
        self.assertIn('suspend_proxy',self.calls.read_text());self.assertNotIn('stop',self.calls.read_text())
        self.assertEqual(self.desired.read_text(),'1')

if __name__=='__main__':unittest.main()
