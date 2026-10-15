import unittest,tempfile,subprocess,os
from pathlib import Path
class Refresh(unittest.TestCase):
 def test_subscription_precedes_routing_and_failures_propagate(self):
  root=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
  text=(root/'usr/bin/xray-lab').read_text();block=text.split('refresh)\n',1)[1].split('\n    ;;',1)[0]
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);log=p/'calls';routing=p/'routing';runner=p/'lab'
   routing.write_text('#!/bin/sh\necho routing >> "$CALLS"\nexit "${ROUTE_RC:-0}"\n');routing.chmod(0o755)
   block=block.replace('/usr/bin/xray-lab-routing',str(routing))
   runner.write_text('#!/bin/sh\nset -e\ncase "$1" in\nsync) echo subscription >> "$CALLS"; exit "${SYNC_RC:-0}";;\nrefresh)\n'+block+'\n;;\nesac\n');runner.chmod(0o755)
   for sync,route,expected,calls in [(0,0,0,['subscription','routing']),(4,0,4,['subscription']),(0,5,5,['subscription','routing'])]:
    log.unlink(missing_ok=True);env={**os.environ,'CALLS':str(log),'SYNC_RC':str(sync),'ROUTE_RC':str(route)}
    r=subprocess.run([str(runner),'refresh'],env=env,capture_output=True)
    self.assertEqual(r.returncode,expected);self.assertEqual(log.read_text().splitlines(),calls)
