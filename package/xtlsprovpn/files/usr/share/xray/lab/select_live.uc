import * as fs from 'fs';
function quote(v){return "'"+replace(''+v,/'/g,"'\\''")+"'";}
function command(args){
    let p=fs.popen(join(' ',map(['timeout','-k','2','10',...args],quote))+' 2>/dev/null','r');
    if(!p)return {ok:false,text:''};let text=p.read('all') || '';return {ok:p.close()==0,text};
}
function api(op,args){let r=command(['env','GOMEMLIMIT=24MiB','GOMAXPROCS=2','/usr/libexec/forkop-xray/xray','api',op,'--server=127.0.0.1:8080','--timeout=3',...(args || [])]);if(!r.ok)die('Xray API недоступен; выбор не сохранён');return r.text;}
function read(path){return json(fs.readfile(path) || 'null');}
function canonical(v){
    if(type(v)=='object'){let out={};for(let k in sort(keys(v)))out[k]=canonical(v[k]);return out;}
    if(type(v)=='array')return map(v,canonical);return v;
}
function stable(c){c=json(sprintf('%J',c));for(let b in c.routing?.balancers || [])if(b.tag=='fx_main'){delete b.selector;delete b.strategy;}return sprintf('%J',canonical(c));}
function write(path,data){let f=fs.open(path+'.new','w',0600);if(!f)die('Не удалось сохранить выбор');let ok=f.write(data);f.close();if(!ok || !fs.rename(path+'.new',path))die('Не удалось сохранить выбор');}
let dir=ARGV[0], location=ARGV[1];
if(!match(location || '',/^(auto|cfg[a-f0-9]{6})$/))die('Неизвестная локация');
let live=read('/var/etc/xray/config.json'), candidate=read(dir+'/config.json');
if(!live || !candidate || stable(live)!=stable(candidate))
    die('Конфигурация процесса отличается от настроек. Примените настройки или перезапустите прокси перед переключением.');
let helper=filter(live.outbounds || [],o=>o.tag=='fx_auto' && o.protocol=='loopback')[0];
if(!helper || !length(filter(live.routing?.balancers || [],b=>b.tag=='fx_auto_pool')))
    die('Для переключения без разрыва один раз перезапустите Xray после обновления приложения.');
let info=json(api('bi',['--json','fx_main'])), old=info?.balancer?.override?.target || '';
let target=location=='auto'?'fx_auto':'fx_node:'+location;
if(location!='auto' && !length(filter(live.outbounds || [],o=>o.tag==target)))die('Узел отсутствует в работающем Xray');
let previous_core=fs.readfile('/etc/config/xray_core'), previous_runtime=fs.readfile('/var/etc/xray/config.json');
let applied=false, persisted=false;
try {
    // Set applied before the RPC: a timeout can occur after the server changed it.
    applied=true;api('bo',['-b','fx_main',target]);
    let effective=json(api('bi',['--json',location=='auto'?'fx_auto_pool':'fx_main']));
    let tags=effective?.balancer?.principleTarget?.tag || effective?.balancer?.principle_target?.tag || [];
    let tag=location=='auto'?tags[0]:target;
    let node=tag?substr(tag,8):'', inbound=filter(live.inbounds || [],x=>x.tag=='fx_probe:'+node && x.listen=='127.0.0.1' && x.protocol=='socks')[0];
    if(!inbound)die('Выбранный узел пока не подтверждён observatory');
    let result=command(['curl','--silent','--show-error','--noproxy','','--proxy','socks5h://127.0.0.1:'+inbound.port,
        '--connect-timeout','3','--max-time','5','--output','/dev/null','--write-out','%{http_code}',
        live.observatory?.probeUrl || 'https://cp.cloudflare.com/generate_204']);
    if(!result.ok || trim(result.text)!='204')die('Новый узел не прошёл HTTPS-проверку; предыдущий выбор возвращён');
    // Save only after successful API and transport checks. No firewall/DNS reload.
    persisted=true;write('/etc/config/xray_core',fs.readfile(dir+'/xray_core'));
    write('/var/etc/xray/config.json',sprintf('%J',candidate));
    write('/var/run/xray-lab-control/selection.json',sprintf('%J',{mode:location=='auto'?'auto':'manual',location,checked:time()}));
    print('Selection applied through Xray API; established connections retained.\n');
} catch(e) {
    let restored=true;
    if(applied){try{api('bo',['-b','fx_main',...(old?[old]:['-r'])]);}catch(err){restored=false;}}
    if(persisted){write('/etc/config/xray_core',previous_core);write('/var/etc/xray/config.json',previous_runtime);}
    if(!restored)die('Не удалось подтвердить возврат выбора через API. Перезапуск не выполнялся; проверьте диагностику.');
    die(trim(''+e));
}
