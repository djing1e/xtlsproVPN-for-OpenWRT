'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const src=fs.readFileSync('package/xtlsprovpn/files/www/luci-static/resources/view/xray/subscription.js','utf8');
function E(tag,attrs={},children=[]){return {tag,attrs,children:Array.isArray(children)?children:[children],value:attrs.value || '',textContent:'',disabled:false};}
function all(n){return n && typeof n==='object'?[n,...n.children.flatMap(all)]:[];}
(async()=>{
 const calls=[];let release;
 const rpc={declare:s=>s.method==='status'?async()=>({configured:true,user_agent:'',hwid_enabled:'1',hwid:''}):(...a)=>{calls.push(a);return new Promise(r=>{release=r;});}};
 const view=new Function('baseclass','rpc','E',src)({extend:v=>v},rpc,E);const page=await view.render(),nodes=all(page);
 const url=nodes.find(n=>n.attrs['aria-label']==='Новая ссылка подписки'),button=nodes.find(n=>n.tag==='button');
 assert.equal(url.value,'');assert.equal(url.attrs.type,'password');assert(!nodes.some(n=>n.attrs.value?.includes('/sub/')));
 url.value='https://example.test/sub/NEW';button.attrs.click();assert.equal(url.value,'');assert.equal(button.disabled,true);assert.equal(calls[0][0],'https://example.test/sub/NEW');
 button.attrs.click();assert.equal(calls.length,1);release({ok:true});await new Promise(r=>setImmediate(r));assert.equal(button.disabled,false);
 console.log('Subscription UI: write-only input, clearing and submit locking passed');
})().catch(e=>{console.error(e);process.exit(1);});
