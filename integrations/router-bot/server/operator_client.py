"""Unprivileged side of the fixed-action local operator queue."""
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

INBOX=Path('/var/lib/xtls-router-bot/operator-inbox')
RESULTS=Path('/var/lib/xtls-router-operator')
CONFIG=Path('/etc/xtls-router-bot/config.json')

def request(action,uid,code='',name='',job=None):
    if action not in ('backup','enroll'):raise ValueError('invalid action')
    if type(uid) is not int:raise ValueError('invalid actor')
    if action=='enroll':
        from connect import pairing
        pairing(code)
        if not valid_name(name):raise ValueError('invalid name')
    if not INBOX.is_dir() or not RESULTS.is_dir():raise ValueError('operator not installed')
    value={'id':job or str(uuid.uuid4()),'action':action,'uid':uid,'created':int(time.time()),'code':code,'name':name}
    # A single slot: hard-link publication refuses to overwrite a queued job.
    fd,path=tempfile.mkstemp(prefix='.request-',dir=INBOX)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream)
        os.chmod(path,0o600)
        os.link(path,INBOX/'request.json')
    finally:Path(path).unlink(missing_ok=True)
    return value['id']

def result(job):
    if not isinstance(job,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',job):raise ValueError('invalid id')
    path=RESULTS/(job+'.json')
    if not path.exists():return None
    value=json.loads(path.read_text())
    if value.get('id')!=job:return None
    return value

def valid_name(name):
    return isinstance(name,str) and 1<=len(name)<=80 and name.strip()==name and not any(ord(c)<32 or ord(c)==127 for c in name)

def router_command(config):
    from connect import router_command as render
    profile=config.get('fleet_profile')
    if not profile:raise ValueError('fleet profile missing')
    return render(profile)
