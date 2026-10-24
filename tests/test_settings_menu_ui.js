'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'../package/xtlsprovpn/files');
const menu=JSON.parse(fs.readFileSync(path.join(root,'usr/share/luci/menu.d/luci-app-forkop-xray.json'),'utf8'));
const route=menu['admin/services/forkop-xray/settings'].action.path;
const source=fs.readFileSync(path.join(root,'www/luci-static/resources/view',route+'.js'),'utf8');
function E(tag,attrs={},children=[]){return {tag,attrs,children:Array.isArray(children)?children:[children],style:{},append(...xs){this.children.push(...xs);},setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;}};}
function all(n){return n && typeof n==='object'?[n,...n.children.flatMap(all)]:[];}
function panel(name){return {load:async()=>({}),render:async()=>E('section',{'data-panel':name},name)};}
async function render(hash,brokenMemory=false){
 const memory=panel('memory');if(brokenMemory)memory.render=async()=>{throw Error('RPC unavailable');};
 const form={Map:class {section(){return {option:()=>({})};}render(){return Promise.resolve(E('section',{'data-panel':'advanced'}));}},NamedSection:class{},Value:class{},Flag:class{}};
 const names=['view','form','uci','widgets','lab','coreUpdate','dnsSettings','schedule','netbird','subscriptionPanel','routingPanel','memoryPanel','E','location'];
 const page=new Function(...names,source)({extend:x=>x},form,{load:async()=>({})},{NetworkSelect:class{}},{style:()=>E('style')},panel('core'),panel('dns'),panel('schedule'),panel('netbird'),panel('subscription'),panel('routing'),memory,E,{hash});
 return page.render(await page.load());
}
(async()=>{
 const page=await render('#memory');const nodes=all(page),tabs=nodes.filter(n=>n.attrs.role==='tab'),panels=nodes.filter(n=>n.attrs.role==='tabpanel');
 assert.deepEqual(tabs.map(t=>t.children[0]),['Подписка','DNS и сеть','Маршрутизация','Автообновление','Ядро','Память','Административный доступ','Дополнительно']);
 const memory=tabs.findIndex(t=>t.children[0]==='Память'),netbird=tabs.findIndex(t=>t.children[0]==='Административный доступ');
 assert.equal(panels[memory].children[0].attrs['data-panel'],'memory');assert.equal(panels[memory].style.display,'');
 assert.equal(panels[netbird].children[0].attrs['data-panel'],'netbird');
 tabs[netbird].attrs.click();assert.equal(panels[netbird].style.display,'');assert.equal(panels[memory].style.display,'none');
 let prevented=false;tabs[netbird].attrs.keydown({key:'ArrowLeft',preventDefault(){prevented=true;}});assert(prevented);assert.equal(panels[memory].style.display,'');
 const dns=all(await render('#dns')).filter(n=>n.attrs.role==='tabpanel');assert.equal(dns[1].style.display,'');
 const broken=all(await render('#memory',true));assert(broken.some(n=>n.children.some(c=>typeof c==='string' && c.includes('RPC unavailable'))));assert(broken.some(n=>n.attrs['data-panel']==='netbird'));
 for(const legacy of ['settings_052.js','settings_transfer2.js']){
  const alias=fs.readFileSync(path.join(root,'www/luci-static/resources/view/xray',legacy),'utf8');
  assert(alias.includes(route.replace('/','.')+' as settingsView'));assert.equal(new Function('settingsView',alias)(page),page);
 }
 console.log('Live settings menu: Memory and NetBird tabs, hash selection, keyboard navigation, RPC error isolation and legacy aliases passed');
})().catch(e=>{console.error(e);process.exit(1);});
