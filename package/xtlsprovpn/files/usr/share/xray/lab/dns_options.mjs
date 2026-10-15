"use strict";
import * as fs from 'fs';
import { cursor } from 'uci';

export const defaults = {
    enabled:'0', protocol:'doh', provider:'cloudflare', servers:[],
    bootstrap:['1.1.1.1','8.8.8.8'], strategy:'ipv4', via_proxy:'1',
    ttl_enabled:'0', ttl:'60', sources:[], output_enabled:'0', output_device:'', disable_quic:'0'
};
export const providers = {
    cloudflare:{name:'Cloudflare',udp:['1.1.1.1','1.0.0.1'],doh:['https://cloudflare-dns.com/dns-query'],dot:['one.one.one.one']},
    google:{name:'Google',udp:['8.8.8.8','8.8.4.4'],doh:['https://dns.google/dns-query'],dot:['dns.google']},
    quad9:{name:'Quad9',udp:['9.9.9.9','149.112.112.112'],doh:['https://dns.quad9.net/dns-query'],dot:['dns.quad9.net']},
    adguard:{name:'AdGuard',udp:['94.140.14.14','94.140.15.15'],doh:['https://dns.adguard-dns.com/dns-query'],dot:['dns.adguard-dns.com']},
    adguard_unfiltered:{name:'AdGuard без фильтрации',udp:['94.140.14.140','94.140.14.141'],doh:['https://unfiltered.adguard-dns.com/dns-query'],dot:['unfiltered.adguard-dns.com']},
    adguard_family:{name:'AdGuard Family',udp:['94.140.14.15','94.140.15.16'],doh:['https://family.adguard-dns.com/dns-query'],dot:['family.adguard-dns.com']},
    yandex:{name:'Яндекс DNS',udp:['77.88.8.8','77.88.8.1'],doh:['https://77.88.8.8/dns-query'],dot:['common.dot.dns.yandex.net']}
};
function fail(s) { die('DNS: '+s); }
function list(v) { return type(v)=='array'?v:v==null || v==''?[]:[v]; }
function device(v) { return type(v)=='string' && match(v,/^[A-Za-z0-9_.-]{1,15}$/)!=null && v!='lo'; }
function host(v) { return iptoarr(v)!=null || match(v,/^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/)!=null; }

export function endpoint(value, protocol) {
    if (type(value)!='string' || !length(value) || length(value)>1024 || match(value,/[[:space:]]/)) fail('неверный адрес DNS');
    if (protocol=='doh') {
        let m=match(value,/^https:\/\/(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(:([0-9]{1,5}))?(\/[^#]*)?$/);
        if (!m) fail('DoH требует HTTPS URL без логина и фрагмента');
        let name=replace(replace(m[1],/^\[/,''),/\]$/,'');
        let port=int(m[3] || 443);
        if (!host(name) || port<1 || port>65535) fail('неверный адрес DoH');
        return {host:name,port,address:value};
    }
    value=replace(value,/^(tls|tcp|udp):\/\//,'');
    let name=value,port=protocol=='dot'?853:53;
    if (!iptoarr(value)) {
        let m=match(value,/^(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(:([0-9]{1,5}))?$/);
        if (!m) fail('неверный адрес DNS');
        name=replace(replace(m[1],/^\[/,''),/\]$/,'');
        if (m[3]) port=int(m[3]);
    }
    if (!host(name) || port<1 || port>65535) fail('неверный хост или порт DNS');
    if (protocol=='udp' && !iptoarr(name)) fail('для UDP укажите IP DNS-сервера');
    let authority=(index(name,':')>=0?'['+name+']':name)+':'+port;
    return {host:name,port,address:protocol=='udp'?name:'tcp://'+authority};
};

function map_options(o) {
    let result={};for (let k in keys(defaults)) result[k]=o[k];return result;
}
export function normalize(input,live) {
    if (type(input)!='object') fail('настройки должны быть объектом');
    for (let key in keys(input)) if (substr(key,0,1)!='.' && defaults[key]==null) fail('неизвестный параметр '+key);
    let o={...defaults,...input};
    for (let k in ['enabled','via_proxy','ttl_enabled','output_enabled','disable_quic']) {
        if (o[k]===true) o[k]='1'; else if (o[k]===false) o[k]='0';
        if (o[k]!='0' && o[k]!='1') fail('неверный переключатель '+k);
    }
    if (index(['udp','tcp','doh','dot'],o.protocol)<0) fail('неверный протокол');
    if (o.provider!='custom' && !providers[o.provider]) fail('неизвестный провайдер');
    if (index(['ipv4','ipv6','auto'],o.strategy)<0) fail('неверная стратегия');
    if (!match(''+o.ttl,/^[0-9]{1,5}$/) || int(o.ttl)>86400) fail('TTL должен быть от 0 до 86400');
    o.ttl=''+int(o.ttl);
    o.servers=list(o.servers); o.bootstrap=list(o.bootstrap);o.sources=uniq(list(o.sources));
    if (length(o.servers)>4 || length(o.bootstrap)<1 || length(o.bootstrap)>4 || length(o.sources)>8) fail('превышено количество адресов или интерфейсов');
    if (o.enabled=='1' && o.provider=='custom' && !length(o.servers)) fail('укажите собственный DNS');
    for (let ip in o.bootstrap) if (type(ip)!='string' || !iptoarr(ip)) fail('bootstrap должен содержать IP без порта');
    if (o.provider=='custom') {for (let value in o.servers) endpoint(value,o.protocol);} else o.servers=[];
    for (let name in o.sources) if (!device(name) || (live && !fs.stat('/sys/class/net/'+name))) fail('интерфейс источника отсутствует: '+name);
    if (type(o.output_device)!='string' || (o.output_enabled=='1' && (!device(o.output_device) || (live && !fs.stat('/sys/class/net/'+o.output_device))))) fail('выходной интерфейс отсутствует');
    // Never persist UCI metadata received through a cursor.
    return { ...map_options(o) };
};
export function resolver_endpoints(o) {
    let values=o.provider=='custom'?o.servers:providers[o.provider][o.protocol=='tcp'?'udp':o.protocol];
    return map(values,v=>endpoint(v,o.protocol));
};
export function load_options() {
    const fixture=getenv('FX_DNS_PREFS_JSON');
    if (fixture) return normalize(json(fs.readfile(fixture)),false);
    const dir=getenv('FX_DNS_CONFIG_DIR');
    if (!fs.stat((dir || '/etc/config')+'/xray_lab_dns')) return null;
    let c=cursor(dir || null);c.load('xray_lab_dns');
    return normalize(c.get_all('xray_lab_dns','main') || {},false);
};
