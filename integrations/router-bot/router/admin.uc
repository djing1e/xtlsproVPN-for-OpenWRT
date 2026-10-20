import * as fs from 'fs';
const RUN='/var/run/xtlspro-bot-admin';
function load(path){try{return json(fs.readfile(path) || '');}catch(e){return null;}}
function uuid(v){return type(v)=='string' && length(v)==36 && !!match(v,/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/);}
function capture(command){let p=fs.popen(command+' 2>/dev/null','r');if(!p)return null;let s=p.read(32769),rc=p.close();return rc==0 && length(s || '')<=32768?s:null;}
function yes(command){return capture(command)!=null;}
let boot=trim(fs.readfile('/proc/sys/kernel/random/boot_id') || '');
let uptime=int(split(fs.readfile('/proc/uptime') || '0',' ')[0]);
let j=load(RUN+'/job.json');
if(j?.boot_id!=boot)j=null;
if(ARGV[0]=='set'){
    let id=ARGV[1],action=ARGV[2],state=ARGV[3],error=ARGV[4] || null;
    if(!uuid(id) || index(['netbird','proxy','reboot'],action)<0 || index(['pending','running','rebooting','done','failed'],state)<0)exit(1);
    if(state!='pending' && (j?.id!=id || j?.action!=action))exit(1);
    let d={id,action,state,error,boot_id:boot,started:j?.id==id?j.started:uptime,updated:time()};
    let f=fs.open(RUN+'/job.json.new','w',0600);if(!f)exit(1);f.write(sprintf('%J',d));f.close();if(!fs.rename(RUN+'/job.json.new',RUN+'/job.json'))exit(1);
    printf('%J\n',d);exit(0);
}
if(ARGV[0]!='status')exit(1);
let nb;try{nb=json(capture('/usr/bin/timeout -k 1 6 /usr/bin/netbird status --json') || '');}catch(e){}
let rescue=yes('/etc/init.d/xray_rescue_watch enabled') && yes('/etc/init.d/xray_rescue_watch running') && trim(capture('uci -q get xray_lab_rescue.main.enabled') || '')=='1';
let enabled=yes('/etc/init.d/netbird-wrapper enabled') || yes('/etc/init.d/netbird enabled');
printf('%J\n',{boot_id:uuid(boot)?boot:null,uptime,job:j || {state:'idle'},
    netbird_connected:nb?.management?.connected===true && nb?.signal?.connected===true,
    netbird_enabled:enabled,rescue_ready:rescue});
