import json,os,socket,subprocess,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
XRAY=os.environ.get('XRAY_TEST_BIN','')

@unittest.skipUnless(XRAY and Path(XRAY).is_file(),'verified native Xray required')
class AutoNativeAPI(unittest.TestCase):
    def test_override_contract_for_both_balancers(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'config.json'
            config.write_text(json.dumps({'log':{'loglevel':'none'},'api':{'tag':'api','services':['RoutingService']},
                'inbounds':[{'tag':'api','listen':'127.0.0.1','port':port,'protocol':'dokodemo-door','settings':{'address':'127.0.0.1'}}],
                'outbounds':[{'tag':'fx_node:'+n,'protocol':'freedom'} for n in ('cfgaaaaaa','cfgbbbbbb')],
                'routing':{'rules':[{'type':'field','inboundTag':['api'],'outboundTag':'api'}],
                    'balancers':[{'tag':tag,'selector':['fx_node:'],'strategy':{'type':'random'}} for tag in ('fx_main','fx_auto_pool')]}}))
            process=subprocess.Popen([XRAY,'run','-c',str(config)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            def api(op,*args):
                return subprocess.run([XRAY,'api',op,'--server=127.0.0.1:'+str(port),'--timeout=1',*args],capture_output=True,text=True,timeout=3)
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    result=api('bi','--json','fx_main')
                    if result.returncode==0:break
                    time.sleep(.1)
                self.assertEqual(result.returncode,0,result.stderr)
                for tag in ('fx_auto_pool','fx_main'):
                    self.assertEqual(api('bo','-b',tag,'fx_node:cfgbbbbbb').returncode,0)
                    data=json.loads(api('bi','--json',tag).stdout)
                    self.assertEqual(data['balancer']['override']['target'],'fx_node:cfgbbbbbb')
                    self.assertEqual(api('bo','-b',tag,'-r').returncode,0)
                    self.assertFalse(json.loads(api('bi','--json',tag).stdout)['balancer']['override'].get('target'))
            finally:
                process.terminate();process.wait(timeout=5)

if __name__=='__main__':unittest.main()
