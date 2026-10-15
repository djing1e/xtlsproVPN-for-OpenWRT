#!/usr/bin/ucode
"use strict";
import * as fs from 'fs';
import { cursor } from 'uci';
const op=ARGV[0],work=ARGV[2],path=getenv('FX_DNS_CACHE_STATE') || '/etc/xray-dns-cache-state.json';
function write(path,data) {
    if(!fs.writefile(path+'.new',data))die('Cannot write DNS cache state');
    fs.chmod(path+'.new',0600);if(!fs.rename(path+'.new',path))die('Cannot commit DNS cache state');
}
function get_cache(c,name) {return (c.get_all('dhcp',name) || {}).cachesize;}
function set_cache(c,name,value) {
    if(value==null)c.delete('dhcp',name,'cachesize');else c.set('dhcp',name,'cachesize',value);
}
let c=cursor(getenv('FX_DNS_DHCP_DIR') || null);c.load('dhcp');
let all=c.get_all('dhcp') || {};
if(op=='sync') {
    const enabled=ARGV[1]=='1',before=fs.readfile(path);
    let state=before?json(before):{version:1,values:{}};
    if(state.version!=1 || type(state.values)!='object')die('Invalid DNS cache state');
    let changes={},names=filter(keys(all),name=>all[name]['.type']=='dnsmasq');
    if(!length(names))die('No dnsmasq instance in DHCP settings');
    for(let name in names) {
        let current=get_cache(c,name),next=current;
        if(enabled) {
            if(index(keys(state.values),name)<0 || current!='0')state.values[name]=current;
            next='0';
        } else if(index(keys(state.values),name)>=0 && current=='0')next=state.values[name];
        if(current!==next) {changes[name]={before:current,after:next};set_cache(c,name,next);}
    }
    write(work+'/cache-journal.json',sprintf('%J',{before,changes}));
    if(enabled)write(path,sprintf('%J\n',state));else fs.unlink(path);
    if(length(keys(changes)) && !c.commit('dhcp'))die('Cannot apply dnsmasq cache size');
} else if(op=='rollback') {
    const raw=fs.readfile(work+'/cache-journal.json');if(!raw)exit(0);
    let journal=json(raw),changed=false;
    for(let name,entry in journal.changes || {}) {
        // Keep unrelated DHCP edits and later manual changes to the cache option.
        if(all[name]?.['.type']=='dnsmasq' && get_cache(c,name)===entry.after) {
            set_cache(c,name,entry.before);changed=true;
        }
    }
    if(changed && !c.commit('dhcp'))die('Cannot restore dnsmasq cache size');
    if(journal.before!=null)write(path,journal.before);else fs.unlink(path);
} else die('Unknown DNS cache operation');
