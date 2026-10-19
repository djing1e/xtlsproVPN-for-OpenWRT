import json,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class Events(unittest.TestCase):
 def test_node_change_is_distinct_from_process_restart(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'run.uc';p.write_text("import { selection_event } from '"+str(ROOT/'package/xtlsprovpn/files/usr/share/xray/lab/selection_events.mjs')+"';let s={mode:'auto',core:{pid:123},nodes:[{id:'cfgbbbbbb',selected:true}],health:{proxy_ok:true,checked:99}};let p={pid:123,nodes:['cfgaaaaaa']};let change=selection_event(p,s,100,'healthy');s.core.pid=456;printf('%J',[change,selection_event(p,s,101,'recovering'),selection_event(change.current,{...s,core:{pid:123}},102,'healthy')]);")
   r=subprocess.run(['ucode',str(p)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr);a=json.loads(r.stdout)
   self.assertEqual(a[0]['event']['type'],'node_changed');self.assertEqual(a[1]['event']['type'],'core_changed');self.assertIsNone(a[2]['event'])
if __name__=='__main__':unittest.main()
