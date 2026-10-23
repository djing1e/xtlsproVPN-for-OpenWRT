#!/usr/bin/ucode
"use strict";
import * as fs from 'fs';
import { cursor } from 'uci';

// Own only default forwarding while interception is active. Preserve split DNS
// and restore only values still matching our last write, including after boot.
const path=getenv('FX_DNS_FORWARD_STATE') || '/etc/xray-dns-forward-state.json';
const op=ARGV[0],c=cursor(getenv('FX_DNS_DHCP_DIR') || null);
c.load('dhcp');
let all=c.get_all('dhcp') || {},raw=fs.readfile(path);
let state=raw?json(raw):{version:1,sections:{}};
if(state.version!=1 || type(state.sections)!='object')die('Invalid DNS forwarding state');
function same(a,b) {return sprintf('%J',a)==sprintf('%J',b);}
function set(name,key,value) {
    if(value==null)c.delete('dhcp',name,key);else c.set('dhcp',name,key,value);
}
function save() {
    if(!fs.writefile(path+'.new',sprintf('%J\n',state)))die('Cannot write DNS forwarding state');
    fs.chmod(path+'.new',0600);
    if(!fs.rename(path+'.new',path))die('Cannot commit DNS forwarding state');
}
let changed=false;
if(op=='up') {
    // Optional section arguments are used by per-instance dnsmasq integration.
    const wanted=slice(ARGV,1);
    for(let name in keys(all)) {
        if(all[name]['.type']!='dnsmasq' || (length(wanted) && index(wanted,name)<0))continue;
        let old=state.sections[name] || {},entry={};
        const current=all[name];
        const servers=type(current.server)=='array'?current.server:current.server==null?[]:[current.server];
        // /#/ is another default, not an exclusive route. Keep named domains.
        const split=filter(servers,s=>index(s,'/')==0 && index(s,'/#/')!=0);
        const next={server:length(split)?split:null,noresolv:'1'};
        for(let key in ['server','noresolv']) {
            const before=old[key] && same(current[key],old[key].after)?old[key].before:current[key];
            entry[key]={before,after:next[key]};
            if(!same(current[key],next[key])) {set(name,key,next[key]);changed=true;}
        }
        state.sections[name]=entry;
    }
    // Persist recovery information before changing DHCP configuration.
    save();
    if(changed && !c.commit('dhcp'))die('Cannot isolate DNS forwarding');
} else if(op=='down') {
    for(let name,entry in state.sections) {
        if(all[name]?.['.type']!='dnsmasq')continue;
        for(let key in ['server','noresolv']) {
            if(entry[key] && same(all[name][key],entry[key].after) && !same(entry[key].before,entry[key].after)) {
                set(name,key,entry[key].before);changed=true;
            }
        }
    }
    if(changed && !c.commit('dhcp'))die('Cannot restore DNS forwarding');
    fs.unlink(path);
} else die('Unknown DNS forwarding operation');
