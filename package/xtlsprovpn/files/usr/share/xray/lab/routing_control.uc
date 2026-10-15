#!/usr/bin/ucode
import * as fs from 'fs';
import { cursor } from 'uci';
import { normalize_rules, rule_keys } from './routing_options.mjs';
import { load_options, defaults } from './dns_options.mjs';
const work=ARGV[1],input=json(fs.readfile(ARGV[0]) || 'null'),options=normalize_rules(input);
let c=cursor(work);c.load('xray_core');
for(let key in rule_keys) {
    if(length(options[key]))c.set('xray_core','general','fx_rule_'+key,options[key]);
    else c.delete('xray_core','general','fx_rule_'+key);
}
if(!c.commit('xray_core'))die('Не удалось подготовить правила');
fs.chmod(work+'/xray_core',0600);
if(!fs.writefile(work+'/dns-options.json',sprintf('%J',load_options() || defaults)))die('Не удалось сохранить параметры DNS');
fs.chmod(work+'/dns-options.json',0600);
