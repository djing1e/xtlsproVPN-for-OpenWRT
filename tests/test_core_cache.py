import hashlib,os,subprocess,tempfile,unittest,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
class Cache(unittest.TestCase):
 def test_cached_candidate_integrity_expiry_and_version(self):
  s=(ROOT/'usr/bin/xray-lab-core').read_text();fn=s[s.index('cached_candidate()'):s.index('cache_candidate()')]
  for case in ('valid','expired','tampered','different'):
   with self.subTest(case=case),tempfile.TemporaryDirectory() as t:
    p=Path(t);cache=p/'cache';cache.mkdir();work=p/'work';work.mkdir();(cache/'xray').write_text('tampered' if case=='tampered' else 'candidate');(cache/'sha256').write_text(hashlib.sha256(b'candidate').hexdigest());(cache/'version').write_text('26.7.11' if case=='different' else '26.7.28');(cache/'expires').write_text(str(int(time.time())+(-100 if case=='expired' else 1800)))
    script=p/'test.sh';script.write_text('set -eu\nCACHE='+str(cache)+'\nWORK='+str(work)+'\nAVAILABLE=26.7.28\nrecord(){ :; }\n'+fn+'\ncached_candidate\n')
    r=subprocess.run(['sh',str(script)],capture_output=True,text=True);self.assertEqual(r.returncode==0,case=='valid',r.stderr);self.assertFalse(cache.exists());self.assertEqual((work/'xray').exists(),case=='valid')
 def test_progress_helper_keeps_numeric_transfer_state(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);s=(ROOT/'usr/share/xray/lab/core_update.uc').read_text().replace('/var/run/xray-lab-control',str(p));(p/'helper.uc').write_text(s)
   r=subprocess.run(['ucode',str(p/'helper.uc'),'progress','1048576','2097152','100','proxy','26.10.10'],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
   d=json.loads((p/'core-progress.json').read_text());self.assertEqual(d['received']/d['total'],0.5);self.assertEqual(d['via'],'proxy');self.assertEqual(d['version'],'26.10.10')
if __name__=='__main__':unittest.main()
