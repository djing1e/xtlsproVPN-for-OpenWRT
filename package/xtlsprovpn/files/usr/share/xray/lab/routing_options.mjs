"use strict";
import { cursor } from 'uci';
export const rule_keys=['block_domains','block_ips','proxy_domains','proxy_ips','direct_domains','direct_ips'];
export function normalize_rules(input) {
    if(type(input)!='object')die('Правила должны быть объектом');
    for(let key in keys(input))if(index(rule_keys,key)<0)die('Неизвестное поле правил');
    let result={};
    for(let key in rule_keys) {
        let raw=input[key] || [], items=type(raw)=='string'?split(raw,/\s+/):raw;
        if(type(items)!='array' || length(items)>256)die('Не более 256 записей в каждом поле');
        let values=[];
        for(let entry in items) {
            if(type(entry)!='string')die('Правило должно быть строкой');
            let value=trim(entry);if(!length(value))continue;
            if(length(value)>512 || (match(value,/[\r\n]/) || index(value,chr(0))>=0))die('Слишком длинное или неверное правило');
            if(index(key,'_ips')>=0) {
                let parts=split(value,'/'),address=iptoarr(parts[0]);
                if(!address || length(parts)>2 || (length(parts)==2 && (!match(parts[1],/^[0-9]{1,3}$/) || int(parts[1])>(length(address)==4?32:128))))die('Неверный IP или подсеть: '+value);
            } else {
                if(!match(value,/^(domain|full|keyword|regexp):/))value='domain:'+value;
                let m=match(value,/^(domain|full|keyword|regexp):(.+)$/);
                if(!m || !length(m[2]))die('Неверное доменное правило');
                if(index(['domain','full'],m[1])>=0 && !match(m[2],/^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/))die('Неверный домен: '+value);
                // Xray validates regexp using its own RE2 implementation at run -test.
                if(index(['domain','full'],m[1])>=0)for(let label in split(m[2],'.'))if(!match(label,/^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/))die('Неверная метка домена');
            }
            push(values,value);
        }
        result[key]=uniq(values);
    }
    return result;
};
export function load_rules() {
    let c=cursor();c.load('xray_core');let g=c.get_all('xray_core','general') || {},o={};
    for(let key in rule_keys)o[key]=g['fx_rule_'+key] || [];
    return normalize_rules(o);
};
