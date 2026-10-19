from pathlib import Path
import json,re,subprocess,sys
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
files=[p for p in root.rglob('*') if p.is_file()]
assert files
for p in files:
 rel=str(p.relative_to(root))
 assert p.name not in ['subscription.json','device-hwid','previous.json','rulesets.json']
 assert not p.name.endswith(('.dat','.zip','.gz','.previous'))
 assert p.stat().st_size<1_000_000,rel
 if rel.startswith(('usr/bin/','etc/init.d/','etc/uci-defaults/','usr/libexec/rpcd/')):
  assert p.stat().st_mode & 0o111 == 0o111, 'Missing executable permissions: '+rel
 if rel.startswith(('usr/bin/','etc/init.d/','etc/uci-defaults/')):subprocess.run(['sh','-n',str(p)],check=True)
 if p.suffix=='.json':json.loads(p.read_text())
 if p.suffix=='.js':
  s=p.read_text();assert 'Forkop Xray' not in s and 'RoscomVPN' not in s,rel
cfg=(root/'etc/config/forkop_xray').read_text()
assert "option subscription_url ''" in cfg and "option hwid ''" in cfg and "option hwid_enabled '1'" in cfg
assert not (root/'www/luci-static/resources/view/xray/core.js').exists()
assert not (root/'usr/share/luci/menu.d/luci-app-xray.json').exists()
menu=json.loads((root/'usr/share/luci/menu.d/luci-app-forkop-xray.json').read_text())
assert not any('dns-network' in k for k in menu)
for item in menu.values():
 if item.get('action',{}).get('type')=='view':assert (root/'www/luci-static/resources/view'/(item['action']['path']+'.js')).exists()
print(f'Source checks passed: {len(files)} files, {sum(p.stat().st_size for p in files)} bytes, no core/assets/subscription identity')
