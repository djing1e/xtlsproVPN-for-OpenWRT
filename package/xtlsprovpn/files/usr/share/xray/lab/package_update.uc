#!/usr/bin/ucode
import * as fs from 'fs';
import { version_ok, release_assets, release_candidate, release_plan } from './package_release.mjs';
const RUN='/var/run/xtlspro-package';
const STATE='/etc/xtlspro-update';
function load(p) {try {return json(fs.readfile(p) || '');} catch(e) {return null;}}
function save(p,v) {
    let f=fs.open(p+'.new','w',0600);
    if (!f) die('Не удалось записать состояние обновления');
    let n=f.write(sprintf('%J',v));f.close();
    if (!n || !fs.rename(p+'.new',p)) die('Не удалось сохранить состояние обновления');
}
function quote(s) {return "'"+replace(''+s,/'/g,"'\\''")+"'";}
function installed() {
    let p=fs.popen('apk info -v xtlsprovpn 2>/dev/null','r');
    let body=p?.read('all') || '';p?.close();
    for (let line in split(body,'\n')) {
        if (index(line,'xtlsprovpn-')==0 && version_ok(substr(line,11))) return substr(line,11);
    }
    return null;
}
function boot() {return trim(fs.readfile('/proc/sys/kernel/random/boot_id') || '');}
function job() {
    let j=load(RUN+'/job.json') || load(STATE+'/last.json') || {state:'idle'};
    if (index(['pending','running'],j.state)>=0) {
        let alive=false;
        if (j.boot==boot() && j.pid>0) {
            let cmd=fs.readfile('/proc/'+j.pid+'/cmdline') || '';
            alive=index(cmd,'/worker')>=0 && index(cmd,'xtls-package.')>=0;
        }
        if (j.boot!=boot() || j.state=='running' && !alive || j.state=='pending' && time()-j.updated>30)
            j={...j,state:'interrupted',message:'Обновление было прервано. Проверьте установленную версию и диагностику; резервная копия настроек сохранена.'};
    }
    return j;
}
let op=ARGV[0];
if (op=='status') {
    let c=load(RUN+'/catalog.json'), v=installed();
    let newer=false;
    if (c && v && time()-c.checked<1800) {
        let p=fs.popen('apk info -e '+quote('xtlsprovpn>='+c.version)+' >/dev/null 2>&1','r');
        newer=p?.close()!=0;
    }
    printf('%J',{installed:v,catalog:c,available:newer,job:job()});
} else if (op=='jobset') {
    let j={state:ARGV[1],action:ARGV[2],phase:ARGV[3],message:ARGV[4],pid:int(ARGV[5]),
        version:ARGV[6] || null,boot:boot(),updated:time()};
    save(RUN+'/job.json',j);
    if (j.action=='install') {
        fs.mkdir(STATE,0700);fs.chmod(STATE,0700);save(STATE+'/last.json',j);
    }
} else if (op=='assets') {
    let a=release_assets(load(ARGV[1]));save(ARGV[2],a);
} else if (op=='candidate') {
    save(ARGV[2],release_candidate(load(ARGV[1])));
} else if (op=='plan') {
    let p=release_plan(load(ARGV[1]),load(ARGV[2]),ARGV[4],ARGV[5]);
    save(ARGV[3],p);
} else if (op=='catalog') {
    let p=load(ARGV[1]);
    if (!version_ok(p?.version)) die('Некорректная версия');
    save(RUN+'/catalog.json',{...p,checked:time()});
} else if (op=='clear') fs.unlink(RUN+'/catalog.json');
else die('Неизвестная операция');
