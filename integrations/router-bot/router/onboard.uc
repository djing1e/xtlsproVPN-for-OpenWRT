import * as fs from 'fs';
import { cursor } from 'uci';
const ROOT='/etc/xtlspro-bot';
function fail(c){printf('%J\n',{error:c});exit(1);}
function load(p){try{return json(fs.readfile(p) || '');}catch(e){return null;}}
function save(p,d){let f=fs.open(p+'.new','w',0600);if(!f)fail('state_failed');f.write(type(d)=='string'?d:sprintf('%J',d));f.close();if(!fs.rename(p+'.new',p))fail('state_failed');}
function uuid(v){return type(v)=='string' && length(v)==36 && !!match(v,/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/);}
function edkey(v){return type(v)=='string' && length(v)==80 && !!match(v,/^ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI[A-Za-z0-9+\/]{43}$/);}
function ipv4(v){if(type(v)!='string')return false;let p=split(v,'.');return length(p)==4 && !length(filter(p,n=>!match(n,/^[0-9]{1,3}$/) || int(n)>255));}
function quote(v){return "'"+replace(''+v,/'/g,"'\\''")+"'";}
function capture(command){let p=fs.popen('/usr/bin/timeout -k 1 12 '+command+' 2>/dev/null','r');if(!p)return null;let text=p.read(16385),rc=p.close();return rc==0 && length(text || '')<=16384?text:null;}
function profile(p){if(type(p)!='object')fail('invalid_profile');if(length(filter(keys(p || {}),k=>index(['schema','profile_id','bot_public_key','rescue_host','rescue_port','rescue_host_key'],k)<0)))fail('invalid_profile');if(p?.schema!=1 || !uuid(p.profile_id) || !edkey(p.bot_public_key) || !ipv4(p.rescue_host) || type(p.rescue_port)!='int' || p.rescue_port<1 || p.rescue_port>65535 || !edkey(p.rescue_host_key))fail('invalid_profile');return p;}
function ssh_port(){
    let cfg=cursor().get_all('dropbear') || {},ports=[];
    for(let k,v in cfg){if(v?.['.type']=='dropbear' && v.enable!='0'){let port=''+(v.Port || '22');if(!match(port,/^[0-9]{1,5}$/) || int(port)<1 || int(port)>65535)fail('ambiguous_ssh_port');if(index(ports,int(port))<0)push(ports,int(port));}}
    if(length(ports)!=1)fail('ambiguous_ssh_port');return ports[0];
}
function pubkey(path){let out=capture('/usr/bin/dropbearkey -y -f '+quote(path)) || '';for(let line in split(out,'\n')){let p=split(trim(line),/[[:space:]]+/);if(edkey(join(' ',slice(p,0,2))))return join(' ',slice(p,0,2));}fail('public_key_missing');}
function call_action(p){let text=capture("printf '%s' "+quote(sprintf('%J',p))+' | /usr/bin/xray-lab-rescue action');let d;try{d=json(text || '');}catch(e){}if(d?.ok!==true)die('rescue_action_failed');}
function rollback(s){
    if(s.before_exists)save('/etc/config/xray_lab_rescue',fs.readfile(ROOT+'/rescue-before-enroll') || '');else fs.unlink('/etc/config/xray_lab_rescue');
    capture('/etc/init.d/xray_rescue_tunnel stop');capture('/etc/init.d/xray_rescue_watch restart');
    if(trim(capture('uci -q get xray_lab_rescue.main.enabled') || '')=='1')try{call_action({action:'open'});}catch(e){}
    s.state='rolled_back';save(ROOT+'/enrollment.json',s);
}
let op=ARGV[0];
if(op=='prepare'){
    let p=profile(load(ARGV[1])),old=load(ROOT+'/profile.json');
    if(old && (old.profile_id!=p.profile_id || old.bot_public_key!=p.bot_public_key || old.rescue_host!=p.rescue_host || old.rescue_port!=p.rescue_port || old.rescue_host_key!=p.rescue_host_key))fail('profile_change_requires_migration');
    let id=trim(fs.readfile(ROOT+'/device-id') || '');
    if(id && !uuid(id))fail('invalid_device_id');
    if(!id){id=trim(fs.readfile('/proc/sys/kernel/random/uuid') || '');if(!uuid(id))fail('uuid_unavailable');save(ROOT+'/device-id',id+'\n');}
    save(ROOT+'/profile.json',p);printf('%J\n',{ok:true,device_id:id});exit(0);
}
if(op=='profile-key'){print(profile(load(ARGV[1])).bot_public_key+'\n');exit(0);}
let p=profile(load(ROOT+'/profile.json')),id=trim(fs.readfile(ROOT+'/device-id') || '');if(!uuid(id))fail('invalid_device_id');
let state=load(ROOT+'/enrollment.json');
if(op=='passport' || op=='identity'){
    let board,nb;try{board=json(capture('ubus call system board') || '');nb=json(capture('/usr/bin/xray-lab-netbird status') || '');}catch(e){}
    let host=split(nb?.netbird_ip || '','/')[0];if(!ipv4(host) || int(split(host,'.')[0])!=100 || int(split(host,'.')[1])<64 || int(split(host,'.')[1])>127)fail('netbird_address_required');
    let model=type(board?.model)=='string'?substr(replace(board.model,/[[:cntrl:]]/g,''),0,120):'OpenWrt';
    printf('%J\n',{schema:1,profile_id:p.profile_id,device_id:id,model,host,port:ssh_port(),host_key:pubkey('/etc/dropbear/dropbear_ed25519_host_key'),rescue_public_key:pubkey('/etc/xtlspro-rescue/id_ed25519'),
        enrollment:state?{transaction:state.transaction,state:state.state,user:state.user,remote_port:state.remote_port}:null});exit(0);
}
if(!uuid(ARGV[1]) || ARGV[1]!=id || !uuid(ARGV[2]))fail('invalid_enrollment');let tx=ARGV[2];
if(op=='apply'){
    let v;try{v=json(fs.stdin.read(4097) || '');}catch(e){}
    if(v?.profile_id!=p.profile_id || v?.transaction!=tx || type(v.user)!='string' || !match(v.user,/^xtls-r-[a-f0-9]{12}$/) || length(v.user)!=19 || type(v.remote_port)!='int' || v.remote_port<22001 || v.remote_port>29999 || type(v.local_port)!='int' || v.local_port!=ssh_port())fail('invalid_enrollment');
    if(state?.transaction==tx){printf('%J\n',{ok:true,state:state.state});exit(0);}
    if(state?.state=='pending')fail('enrollment_busy');
    state={transaction:tx,state:'pending',user:v.user,remote_port:v.remote_port,before_exists:!!fs.stat('/etc/config/xray_lab_rescue')};
    save(ROOT+'/rescue-before-enroll',fs.readfile('/etc/config/xray_lab_rescue') || '');save(ROOT+'/enrollment.json',state);
    try{call_action({action:'configure',host:p.rescue_host,port:''+p.rescue_port,user:v.user,remote_port:''+v.remote_port,local_port:''+v.local_port,host_key:p.rescue_host_key});call_action({action:'open'});}
    catch(e){rollback(state);fail('enrollment_apply_failed');}
    printf('%J\n',{ok:true,state:'pending'});exit(0);
}
if(state?.transaction!=tx)fail('transaction_mismatch');
if(op=='commit'){if(index(['pending','enrolled'],state.state)<0)fail('transaction_mismatch');state.state='enrolled';save(ROOT+'/enrollment.json',state);printf('%J\n',{ok:true,state:'enrolled'});exit(0);}
if(op=='rollback'){if(state.state!='pending')fail('transaction_mismatch');rollback(state);printf('%J\n',{ok:true,state:'rolled_back'});exit(0);}
fail('unsupported_command');
