'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync('package/xtlsprovpn/files/www/luci-static/resources/view/xray/memory.js','utf8');
function E(tag,attrs={},children=[]){
 const node={tag,attrs,children:Array.isArray(children)?children:[children],style:{},checked:!!attrs.checked,value:attrs.value || '',textContent:'',disabled:false,replaceChildren(...nodes){this.children=nodes;this.value=(nodes.find(n=>n.attrs.selected) || nodes[0])?.attrs.value || '';}};
 if(tag==='select'){const option=node.children.find(x=>x.attrs.selected) || node.children[0];node.value=option?.attrs.value || '';}
 return node;
}
function all(node){return node && typeof node==='object'?[node,...node.children.flatMap(all)]:[];}
(async()=>{
 let data={installed:false,enabled:false,managed:true,size_mb:128,algorithm:'lzo',algorithms:['lzo'],active:false,total_kb:239568,available_kb:61720,swaps:[],job:{state:'idle'}};
 let poller,calls=[],failure=false;
 const rpc={declare:s=>s.method==='status'?async()=>data:async(...args)=>{calls.push(args);return failure?{error:'Недостаточно свободной RAM'}:{ok:true};}};
 const module=new Function('baseclass','rpc','poll','E',source)({extend:x=>x},rpc,{add:f=>{poller=f;}},E);
 const page=await module.render(),nodes=all(page);
 const enabled=nodes.find(n=>n.attrs['aria-label']==='Включить ZRAM');
 const size=nodes.find(n=>n.attrs['aria-label']==='Размер ZRAM');
 const button=nodes.find(n=>n.tag==='button');
 assert.equal(calls.length,0);assert.equal(enabled.checked,true);assert.equal(size.value,'128');
 await button.attrs.click();assert.deepEqual(calls,[['1','128','lzo']]);assert.equal(button.disabled,true);
 data={...data,algorithms:['lzo','lz4'],installed:true,enabled:true,active:true,active_algorithm:'lzo',swaps:[{size_kb:131068,used_kb:0,priority:100}],job:{state:'done',message:'Включён'}};
 await poller();assert.equal(button.disabled,false);assert(nodes.find(n=>n.attrs['aria-label']==='Алгоритм ZRAM').children.some(n=>n.attrs.value==='lz4'));assert(nodes.some(n=>n.textContent.includes('ZRAM: 128.0 МиБ')));
 enabled.checked=false;failure=true;await button.attrs.click();assert.deepEqual(calls.at(-1),['0','128','lzo']);
 assert(nodes.some(n=>n.textContent.includes('Недостаточно свободной RAM')));
 await poller();assert(nodes.some(n=>n.textContent.includes('Недостаточно свободной RAM')));
 data={...data,managed:false};await poller();assert.equal(button.disabled,true);assert.equal(enabled.disabled,true);
 console.log('ZRAM UI: explicit install, size, busy state, runtime status, disable errors and foreign configuration passed');
})().catch(e=>{console.error(e);process.exit(1);});
