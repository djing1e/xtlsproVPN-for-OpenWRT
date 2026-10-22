#!/usr/bin/env python3
"""Create a release compatibility manifest from the exact APK being published."""
import argparse
import hashlib
import json
from pathlib import Path
import re

p = argparse.ArgumentParser()
p.add_argument('apk', type=Path)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--installed-size-kb', type=int, default=4096,
               help='Conservative upper bound for installed application files, without dependencies')
a = p.parse_args()
m = re.fullmatch(r'xtlsprovpn-(\d+\.\d+\.\d+)-r(\d+)\.apk', a.apk.name)
if not m or not 1024 <= a.installed_size_kb <= 32768:
    p.error('Expected a stable xtlsprovpn APK and installed size between 1024 and 32768 KiB')
data = a.apk.read_bytes()
if not 0 < len(data) <= 8388608:
    p.error('APK must be between 1 byte and 8 MiB')
manifest = {'schema':1,'tag':'v'+m[1],'version':m[1]+'-r'+m[2],
            'openwrt':['25.12.5','25.12.6'],'architectures':['aarch64'],
            'installed_size_kb':a.installed_size_kb,
            'apk':{'name':a.apk.name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}}
a.output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
