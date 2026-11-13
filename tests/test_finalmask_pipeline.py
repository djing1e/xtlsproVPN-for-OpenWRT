import hashlib,json,subprocess,unittest,urllib.parse
import test_native_catalogue as native
from test_finalmask import MASK

class FinalMaskPipeline(unittest.TestCase):
    def setUp(self):
        self.enc='none';self.pub='A'*43;native.CatalogueTests.setUp(self)
    prepare=native.CatalogueTests.prepare
    generate=native.CatalogueTests.generate
    def test_uri_to_catalogue_to_native_xray_preserves_finalmask(self):
        for transport in ('raw','xhttp'):
            with self.subTest(transport=transport):
                query={'type':transport,'security':'reality' if transport=='raw' else 'tls','sni':'origin.example.test','fm':json.dumps(MASK)}
                if transport=='raw':query['pbk']='A'*43
                link='vless://00000000-0000-4000-8000-000000000001@node.example.test:443?'+urllib.parse.urlencode(query)
                path=self.d/'input';path.write_text(link)
                code="let fs=require('fs');printf('%J',require('parser').parse(fs.readfile(ARGV[0])));"
                result=subprocess.run(['ucode','-L',str(native.BASE/'files/usr/lib/forkop-xray'),'-e',code,str(path)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                node=json.loads(result.stdout)['nodes'][0];node['id']=hashlib.sha256(node.pop('identity').encode()).hexdigest();self.nodes=[node]
                self.prepare();config=self.generate()
                outbounds=[o for o in config['outbounds'] if o['protocol']=='vless'];self.assertTrue(outbounds)
                for outbound in outbounds:
                    self.assertEqual(outbound['streamSettings']['finalmask'],MASK)
                    self.assertEqual(outbound['streamSettings']['sockopt']['mark'],253)

if __name__=='__main__':unittest.main()
