import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
MOCK=r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);name=Path(sys.argv[0]).name;a=sys.argv[1:];scenario=os.environ['SCENARIO']
if name=='crontab':
 if a==['-l']:sys.stdout.write((r/'cron').read_text())
 else:
  if scenario=='cron-write-fail':sys.exit(1)
  (r/'cron').write_text(Path(a[0]).read_text())
elif name in ('sub','routing'):
 with (r/'calls').open('a') as f:f.write(name+'\n')
 print(name+' completed')
 sys.exit(1 if scenario==name+'-fail' else 0)
elif name=='pidof':print('23785')
elif name=='ucode':print(json.dumps({'proxy_ok':scenario!='health-fail'}))
elif name=='jsonfilter':
 d=json.loads(Path(a[a.index('-i')+1]).read_text())
 for k in a[a.index('-e')+1].removeprefix('@.').split('.'):d=d[k]
 print(str(d).lower())
else:raise RuntimeError(name)
'''
class CronHarness(unittest.TestCase):
    def test_one_shot_worker_preserves_cron_and_reports_failures(self):
        for scenario in ('success','sub-fail','routing-fail','health-fail','cron-write-fail'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                r=Path(temp);tools=r/'tools';tools.mkdir();run=r/'run';run.mkdir();work=r/'report.ABC';work.mkdir()
                for name in ('crontab','sub','routing','pidof','ucode','jsonfilter'):
                    p=tools/name;p.write_text(MOCK);p.chmod(0o755)
                original='0 */6 * * * /usr/bin/xray-lab sync # xray-lab-subscription-sync\n\n15 */6 * * * /usr/bin/xray-lab-routing update # xray-lab-routing-update\n0 3 * * * /bin/true # unrelated\n'
                tag='# xtls-cron-smoke-test:report.ABC'
                (work/'tag').write_text(tag+'\n');(work/'original.cron').write_text(original)
                (r/'cron').write_text(original+'* * * * * /bin/sh /test worker '+tag+'\n')
                schedule=r/'schedule';schedule.write_text('unchanged settings')
                (work/'schedule-before.sha256').write_text(hashlib.sha256(schedule.read_bytes()).hexdigest()+'  '+str(schedule)+'\n')
                (r/'last').write_text(str(work)+'\n')
                source=(ROOT/'scripts/test-schedule-cron-lab.sh').read_text()
                source=source.replace('RUN=/var/run/xray-lab-control','RUN='+str(run)).replace('LAST=/root/xtls-cron-test-last','LAST='+str(r/'last')).replace('/root/xtls-cron-test.',str(r/'report.'))
                source=source.replace('/usr/bin/xray-lab-routing',str(tools/'routing')).replace('/usr/bin/xray-lab',str(tools/'sub')).replace('/usr/bin/ucode',str(tools/'ucode'))
                script=work/'test.sh';script.write_text(source)
                env={**os.environ,'TEST_ROOT':str(r),'SCENARIO':scenario,'PATH':str(tools)+':'+os.environ['PATH']}
                worker=subprocess.run(['sh',str(script),'worker'],env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(worker.returncode==0,scenario!='cron-write-fail',worker.stderr)
                self.assertEqual((r/'calls').read_text(),'sub\nrouting\n')
                # Cron may invoke the same entry again while a long first run is still active.
                again=subprocess.run(['sh',str(script),'worker'],env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(again.returncode,0);self.assertEqual((r/'calls').read_text(),'sub\nrouting\n')
                if scenario!='cron-write-fail':self.assertEqual((r/'cron').read_text(),original)
                result=subprocess.run(['sh',str(script),'verify'],env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode==0,scenario=='success',result.stdout+result.stderr)
                self.assertEqual('PASS:' in result.stdout,scenario=='success')

if __name__=='__main__':unittest.main()
