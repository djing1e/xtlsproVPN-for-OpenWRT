import hashlib,os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ConfigWatch(unittest.TestCase):
 def test_generator_only_change_changes_procd_file_signature(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);uci=d/'uci';runtime=d/'config.json';uci.write_text('same UCI');runtime.write_text('{"old":true}')
   src=(ROOT/'package/xtlsprovpn/files/etc/init.d/xray_core').read_text().replace('/etc/config/xray_core',str(uci)).replace('/var/etc/xray/config.json',str(runtime))
   script=d/'run.sh';script.write_text(src+'\nlogger(){ :; };procd_open_instance(){ :; };procd_close_instance(){ :; };procd_append_param(){ :; };procd_set_param(){ if [ "$1" = file ]; then shift; sha256sum "$@"; fi; };start_xray /unused/xray\n')
   first=subprocess.check_output(['sh',str(script)],text=True);runtime.write_text('{"new":true}');second=subprocess.check_output(['sh',str(script)],text=True)
   self.assertEqual(uci.read_text(),'same UCI');self.assertNotEqual(first,second)
if __name__=='__main__':unittest.main()
