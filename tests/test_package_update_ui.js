'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync('package/xtlsprovpn/files/www/luci-static/resources/view/xray/app_update.js','utf8');
function E(tag,attrs={},children=[]) {
    return {tag,attrs,children:Array.isArray(children)?children:[children],style:{},disabled:false,textContent:'',
        setAttribute(k,v){this.attrs[k]=v;}};
}
function all(n){return n && typeof n==='object'?[n,...n.children.flatMap(all)]:[];}
async function main(){
    let current={installed:'1.1.1-r1',available:true,job:{state:'idle'},catalog:{version:'1.1.2-r1',sha256:'a'.repeat(64),release_url:'https://github.com/djing1e/xtlsproVPN-for-OpenWRT/releases/tag/v1.1.2'}};
    const calls=[];let poller,modal,offline=false;
    const rpc={declare(spec){return spec.method==='status'?async()=>{
        if(offline)throw Error('disconnected');return current;
    }:async(...args)=>{calls.push(args);current={...current,job:{state:'running',message:'Установка'}};return {ok:true};};}};
    const page=new Function('view','rpc','poll','ui','E',source)({extend:x=>x},rpc,{add:fn=>{poller=fn;}},
        {showModal:(title,children)=>{modal=E('modal',{},children);},hideModal:()=>{}},E);
    const dom=await page.render(current);const nodes=all(dom);
    const install=nodes.find(n=>n.tag==='button'&&n.children[0]==='Установить обновление');
    assert.equal(install.disabled,false);install.attrs.click();assert.equal(calls.length,0);
    const confirm=all(modal).find(n=>n.tag==='button'&&n.children[0]==='Обновить');await confirm.attrs.click();
    assert.deepEqual(calls[0],['install','1.1.2-r1','a'.repeat(64)]);
    assert.equal(install.disabled,true);
    offline=true;await poller();assert.equal(install.disabled,true);
    assert(nodes.some(n=>n.textContent.includes('Ожидаем связь')));
    offline=false;current={...current,installed:'1.1.2-r1',available:false,job:{state:'done',message:'Готово'}};
    await poller();assert.equal(install.disabled,true);
    assert(nodes.some(n=>n.textContent.includes('1.1.2-r1')));
    current={...current,available:true,job:{state:'failed',message:'Ошибка установки'}};await poller();
    assert.equal(install.disabled,false);assert(nodes.some(n=>n.textContent==='Ошибка установки'));
    console.log('Package update UI: explicit confirmation, pinned version/hash, busy state and reconnect passed');
}
main().catch(e=>{console.error(e);process.exit(1);});
