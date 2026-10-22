import copy
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
class SubscriptionTransport(unittest.TestCase):
    def request(self,direct=35,proxy=0,http='000',fallback='127.0.0.1:11503'):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            source=(FILES/'usr/lib/forkop-xray/main.uc').read_text()
            function=source[source.index('function fetch(s)'):source.index('function summary()')]
            prelude="let fs=require('fs'),run_dir=ARGV[0];function quote(s){return chr(39)+replace(''+s,/'/g,chr(39)+chr(92)+chr(39)+chr(39))+chr(39);}function command(a){return join(' ',map(a,quote));}function accept(){print('accepted');}\n"
            (p/'run.uc').write_text(prelude+function+"fetch({subscription_url:'https://secret.test/sub/PRIVATE-TOKEN',user_agent:'Xray/test',hwid:'router-12345'});")
            (p/'curl').write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:];root=Path(os.environ['REQUEST_ROOT'])
with (root/'requests').open('a') as f:f.write(json.dumps({'args':a,'headers':Path(a[a.index('--config')+1]).read_text()})+'\\n')
proxy='--proxy' in a
print('200' if proxy and int(os.environ['PROXY_RC'])==0 else os.environ['DIRECT_HTTP'],end='')
sys.exit(int(os.environ['PROXY_RC'] if proxy else os.environ['DIRECT_RC']))
''')
            (p/'curl').chmod(0o755)
            r=subprocess.run(['ucode',str(p/'run.uc'),str(p)],capture_output=True,text=True,
                env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],REQUEST_ROOT=str(p),DIRECT_RC=str(direct),PROXY_RC=str(proxy),DIRECT_HTTP=http,FX_FALLBACK_SOCKS=fallback))
            calls=[json.loads(s) for s in (p/'requests').read_text().splitlines()]
            self.assertFalse((p/'curl.conf').exists())
            self.assertNotIn('PRIVATE-TOKEN',r.stdout+r.stderr)
            for c in calls:
                self.assertNotIn('--insecure',c['args']);self.assertNotIn('-k',c['args'])
                self.assertIn('--proto',c['args']);self.assertIn('=https',c['args'])
                self.assertIn('--proto-redir',c['args']);self.assertIn('--config',c['args'])
                self.assertNotIn('PRIVATE-TOKEN',' '.join(c['args']))
            return r,calls

    def test_handshake_failure_uses_proxy_with_same_identity(self):
        r,calls=self.request()
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['headers'],calls[1]['headers'])
        self.assertEqual(calls[0]['args'][calls[0]['args'].index('--noproxy')+1],'*')
        a=calls[1]['args'];self.assertEqual(a[a.index('--proxy')+1],'socks5h://127.0.0.1:11503')
        self.assertEqual(a[len(a)-1-a[::-1].index('--noproxy')+1],'')

    def test_direct_success_does_not_retry(self):
        r,calls=self.request(direct=0,http='200');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(len(calls),1)

    def test_dns_connect_timeout_still_retry(self):
        for rc in [6,7,28]:
            with self.subTest(rc=rc):
                r,calls=self.request(direct=rc);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(len(calls),2)

    def test_certificate_http_and_auth_failures_never_retry(self):
        for rc,http in [(60,'000'),(51,'000'),(22,'403'),(22,'401'),(35,'403')]:
            with self.subTest(rc=rc,http=http):
                r,calls=self.request(direct=rc,http=http);self.assertNotEqual(r.returncode,0);self.assertEqual(len(calls),1)

    def test_failure_reports_both_transports(self):
        r,calls=self.request(direct=35,proxy=7);self.assertNotEqual(r.returncode,0)
        self.assertIn('curl=7',r.stderr);self.assertIn('direct curl=35',r.stderr);self.assertIn('fallback=proxy',r.stderr)

    def test_missing_or_nonlocal_fallback_is_not_used(self):
        for fallback in ['', '192.168.5.1:1080', '127.0.0.1:1;bad']:
            with self.subTest(fallback=fallback):
                r,calls=self.request(fallback=fallback);self.assertNotEqual(r.returncode,0);self.assertEqual(len(calls),1)

    def test_fallback_uses_only_healthy_pinned_listeners(self):
        state={'core':{'running':True},'nodes':[{'id':'a','alive':True,'selected':False,'rtt_ms':10},{'id':'b','alive':True,'selected':True,'rtt_ms':30}]}
        runtime={'inbounds':[],'outbounds':[],'routing':{'rules':[]}}
        for i,node in enumerate(['a','b']):
            runtime['inbounds'].append({'tag':'fx_probe:'+node,'listen':'127.0.0.1','port':11500+i,'protocol':'socks','settings':{'auth':'noauth','udp':False}})
            runtime['outbounds'].append({'tag':'fx_node:'+node,'protocol':'vless'})
            runtime['routing']['rules'].append({'inboundTag':['fx_probe:'+node],'outboundTag':'fx_node:'+node})
        def choose(s,r):
            with tempfile.TemporaryDirectory() as temp:
                p=Path(temp);(p/'input').write_text(json.dumps([s,r]))
                (p/'run.uc').write_text("import { subscription_proxy } from '"+str(FILES/'usr/share/xray/lab/subscription_transport.mjs')+"';let a=json(require('fs').readfile(ARGV[0]));print(subscription_proxy(a[0],a[1]));")
                v=subprocess.run(['ucode',str(p/'run.uc'),str(p/'input')],capture_output=True,text=True)
                self.assertEqual(v.returncode,0,v.stderr);return v.stdout
        self.assertEqual(choose(state,runtime),'127.0.0.1:11501')
        r=copy.deepcopy(runtime);r['routing']['rules'].pop();self.assertEqual(choose(state,r),'127.0.0.1:11500')
        s=copy.deepcopy(state);s['nodes'][1]['alive']=False;self.assertEqual(choose(s,runtime),'127.0.0.1:11500')
        s['nodes'][0]['alive']=False;self.assertEqual(choose(s,runtime),'')
        s=copy.deepcopy(state);s['core']['running']=False;self.assertEqual(choose(s,runtime),'')
        for change in [{'listen':'0.0.0.0'},{'port':70000},{'settings':{'auth':'password','udp':False}}]:
            r=copy.deepcopy(runtime)
            for inbound in r['inbounds']:inbound.update(change)
            self.assertEqual(choose(state,r),'')

if __name__=='__main__':unittest.main()
