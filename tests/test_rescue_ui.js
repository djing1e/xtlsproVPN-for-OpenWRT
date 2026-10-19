'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/../package/xtlsprovpn/files/www/luci-static/resources/view/xray/rescue.js','utf8');
function E(tag,attrs={},children=[]){return {tag,attrs,children:Array.isArray(children)?children:[children],value:attrs.value || '',disabled:false,textContent:''};}
function all(n){return n && typeof n==='object'?[n,...n.children.flatMap(all)]:[];}
async function main(){
 let polls=[],requests=[],release;
 const data={enabled:true,host:'192.0.2.1',port:'62152',user:'xtls-rescue',remote_port:'22001',local_port:'222',host_key:'ssh-ed25519 PUBLIC',public_key:'ssh-ed25519 ROUTER',state:{reason:'standby'}};
 const rpc={declare:s=>s.method==='status'?async()=>data:(...a)=>{requests.push(a);return new Promise(r=>release=r);}};
 const view=new Function('baseclass','rpc','poll','E',source)({extend:x=>x},rpc,{add:f=>polls.push(f)},E);
 const nodes=all(await view.render());
 assert.equal(nodes.find(n=>n.attrs['aria-label']==='Публичный ключ роутера').value,data.public_key);
 assert.equal(nodes.find(n=>n.attrs['aria-label']==='local_port').value,'222');
 const button=nodes.find(n=>n.tag==='button' && n.children.includes('Открыть на 30 минут'));
 const first=button.attrs.click();button.attrs.click();assert.equal(requests.length,1);
 assert.equal(requests[0][0],'open');assert.equal(requests[0][5],'222');assert.equal(button.disabled,true);
 release({error:'Сервер недоступен'});await first;
 assert.equal(button.disabled,false);assert(nodes.some(n=>n.textContent==='Сервер недоступен'));
 await polls[0]();assert.equal(requests.length,1);
 assert(!source.includes('private_key'));console.log('Rescue UI: ports, public key, action serialization, errors and polling passed');
}
main().catch(e=>{console.error(e);process.exit(1);});
