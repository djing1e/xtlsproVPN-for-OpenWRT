#!/usr/bin/ucode
"use strict";
import * as fs from 'fs';
import { cursor } from 'uci';
import { load_rules } from './routing_options.mjs';
import { defaults, providers, normalize, load_options } from './dns_options.mjs';
import { load_config } from '../common/config.mjs';
import { dns_probe } from './dns_probe.mjs';
const root='/var/run/xray-lab-control';
function load(path,fallback) {try{return json(fs.readfile(path) || '') || fallback;}catch(e){return fallback;}}
function save(path,data) {
    if (!fs.writefile(path+'.new',sprintf('%J\n',data))) die('Cannot write DNS state');
    fs.chmod(path+'.new',0600);if(!fs.rename(path+'.new',path))die('Cannot save DNS state');
}
const op=ARGV[0];
if (op=='status') {
    let options=load_options() || defaults;
    let job=load(root+'/dns-job.json',{state:'idle'});
    if (job.state=='running' && (!job.pid || !fs.stat('/proc/'+job.pid))) {
        job.state='interrupted';job.message='Операция прервана. Проверьте DNS и диагностику.';
    }
    if (job.state=='pending' && time()-job.updated>10) {job.state='failed';job.message='Операция не запустилась';}
    let devices=[];
    for (let path in fs.glob('/sys/class/net/*') || []) {
        let name=substr(path,15);if (name!='lo') push(devices,name);
    }
    let sources=[],source_error;
    try { sources=load_config().general?.tproxy_ifaces_v4 || []; }
    catch (e) { source_error=''+e; }
    printf('%J\n',{options,providers,devices:sort(devices),sources,source_error,job,rules:load_rules()});
} else if (op=='stage') {
    let input=load(ARGV[1],null),options=normalize(input,true),dir=ARGV[2];
    if (!fs.writefile(dir+'/xray_lab_dns',"config settings 'main'\n"))die('Cannot create DNS settings');
    let c=cursor(dir);c.load('xray_lab_dns');
    for(let k,v in options) if(type(v)!='array' || length(v)) c.set('xray_lab_dns','main',k,v);
    if(!c.commit('xray_lab_dns'))die('Cannot stage DNS settings');
    fs.chmod(dir+'/xray_lab_dns',0600);
    save(dir+'/options.json',options);
} else if(op=='probe-config') {
    let c=load(ARGV[1],null);
    if(!c)die('Missing candidate config');
    let plan=dns_probe(c,load(ARGV[4],null),load(ARGV[5],null),load(ARGV[6],null),time());
    plan.config.log={loglevel:'info',access:'none',error:ARGV[3]};
    save(ARGV[2],plan.config);
    delete plan.config;
    save(ARGV[7],plan);
} else if(op=='jobset') {
    let before=load(root+'/dns-job.json',{});
    save(root+'/dns-job.json',{
        id:ARGV[1],state:ARGV[2],action:ARGV[3],phase:ARGV[4],message:ARGV[5],
        pid:int(ARGV[6]),updated:time(),started:ARGV[2]=='pending'?time():before.started || time()
    });
} else die('Unknown DNS operation');
