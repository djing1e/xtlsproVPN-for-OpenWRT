import base64,copy,json,unittest,urllib.parse
import test_xhttp_parser as parser_tests

MASK={'tcp':[{'type':'fragment','settings':{'packets':'tlshello','length':'100-200','delay':'10-20'}}]}

class FinalMaskParser(unittest.TestCase):
    setUp=parser_tests.XHTTP.setUp
    parse=parser_tests.XHTTP.parse
    uri=parser_tests.XHTTP.uri
    def raw(self,**patch):
        return self.uri(type='raw',security='reality',pbk='A'*43,**patch)
    def test_remnawave_fm_uri_preserved_for_raw_and_xhttp(self):
        for link in (self.raw(fm=json.dumps(MASK)),self.uri(fm=json.dumps(MASK))):
            r=self.parse(link);self.assertFalse(r['skipped']);self.assertEqual(r['nodes'][0]['outbound']['streamSettings']['finalmask'],MASK)
    def test_base64_subscription_and_form_encoded_json(self):
        link=self.raw(fm=json.dumps(MASK))
        result=self.parse(base64.b64encode(link.encode()).decode())
        self.assertEqual(result['nodes'][0]['outbound']['streamSettings']['finalmask'],MASK)
        # The helper adds a display-name fragment; place the query before it.
        form=self.raw().split('#')[0]+'&fm='+urllib.parse.quote_plus(json.dumps(MASK))
        self.assertEqual(self.parse(form)['nodes'][0]['outbound']['streamSettings']['finalmask'],MASK)
    def test_json_and_case_alias_preserve_masks_and_quic_settings(self):
        obj=self.parse(self.raw())['nodes'][0]['outbound']
        mask=copy.deepcopy(MASK);mask.update(udp=[{'type':'salamander','settings':{'password':'mask+value'}}],quicParams={'congestion':'bbr','debug':False})
        for field in ('finalmask','finalMask'):
            sample=copy.deepcopy(obj);sample['streamSettings'][field]=mask
            result=self.parse(json.dumps(sample));self.assertEqual(result['nodes'][0]['outbound']['streamSettings']['finalmask'],mask)
            self.assertNotIn('finalMask',result['nodes'][0]['outbound']['streamSettings'])
    def test_mask_variants_do_not_collide_with_legacy_endpoint_identity(self):
        other=copy.deepcopy(MASK);other['tcp'][0]['settings']['length']='200-300'
        r=self.parse('\n'.join((self.raw(),self.raw(fm=json.dumps(MASK)),self.raw(fm=json.dumps(other)))))
        self.assertEqual(len(r['nodes']),3);self.assertEqual(len({n['identity'] for n in r['nodes']}),3)
        self.assertEqual(len(json.loads(r['nodes'][0]['identity'])),4)
    def test_equivalent_object_order_is_deduplicated(self):
        reordered={'tcp':[{'settings':{'delay':'10-20','length':'100-200','packets':'tlshello'},'type':'fragment'}]}
        r=self.parse(self.raw(fm=json.dumps(MASK))+'\n'+self.raw(finalmask=json.dumps(reordered)))
        self.assertEqual(len(r['nodes']),1);self.assertFalse(r['skipped'])
    def test_encoded_plus_and_zero_values_are_not_changed(self):
        mask={'udp':[{'type':'salamander','settings':{'password':'a+b / c','zero':0,'flag':False}}]}
        r=self.parse(self.raw(fm=json.dumps(mask)));self.assertEqual(r['nodes'][0]['outbound']['streamSettings']['finalmask'],mask)
    def test_malformed_oversized_and_ambiguous_masks_skip_only_bad_entries(self):
        invalid=['not-json','null','[]','"secret-value"',json.dumps({'tcp':{}}),json.dumps({'tcp':[{'type':'fragment','settings':[]}]}),json.dumps({'unexpected':True}),json.dumps({'tcp':[{'type':'fragment'}]*33}),json.dumps({'tcp':[{'type':'fragment','settings':{'secret':'x'*65536}}]})]
        links=[self.raw()]+[self.raw(fm=v) for v in invalid]+[self.raw(fm=json.dumps(MASK),finalmask=json.dumps(MASK))]
        result=self.parse('\n'.join(links));self.assertEqual(len(result['nodes']),1);self.assertEqual(len(result['skipped']),len(links)-1)
        for row in result['skipped']:
            self.assertIn('FinalMask',row['reason']);self.assertNotIn('secret-value',row['reason']);self.assertNotIn('00000000-',row['reason'])

if __name__=='__main__':unittest.main()
