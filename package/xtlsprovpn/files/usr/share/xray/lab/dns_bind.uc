#!/usr/bin/ucode
"use strict";
import { cursor } from 'uci';

// NetBird uses wt0 even with client DNS management disabled. Keep its DNS
// listener separate from dnsmasq, including when wt0 appears after boot.
const c=cursor(getenv('FX_DNS_DHCP_DIR') || null);
if(!c.load('dhcp'))die('Cannot load DHCP configuration');
let changed=false;
for(let name,section in (c.get_all('dhcp') || {})) {
    if(section['.type']!='dnsmasq')continue;
    let excluded=section.notinterface;
    excluded=type(excluded)=='array'?excluded:excluded==null?[]:[excluded];
    if(index(excluded,'wt0')<0) {
        c.set('dhcp',name,'notinterface',[...excluded,'wt0']);changed=true;
    }
    if(section.nonwildcard!='1') {
        c.set('dhcp',name,'nonwildcard','1');changed=true;
    }
}
if(changed && !c.commit('dhcp'))die('Cannot save NetBird DNS listener isolation');
print(changed?'changed\n':'unchanged\n');
