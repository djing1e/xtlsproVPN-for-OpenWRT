'use strict';
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path');
const runtime=require('./fixtures/luci-loader-128a781');
const root=path.join(__dirname,'../package/xtlsprovpn/files/www/luci-static/resources/view');
// LuCI's loader uses its global String.format helper for URLs and errors.
String.prototype.format=function(...args){let i=0;return this.replace(/%[sd]/g,()=>String(args[i++]));};
function loader(overrides={}) {
 const classes={rpc:{declare:()=>async()=>({})},ui:{},poll:{},form:{},uci:{},'tools.widgets':{}};
 let starts=0;
 const Request={get:async url=>{
  const name=url.slice('/resources/'.length,-3).replaceAll('/','.');
  const source=overrides[name] ?? fs.readFileSync(path.join(root,name.slice(5).replaceAll('.','/')+'.js'),'utf8');
  return {ok:true,url,text:()=>source};
 }};
 const {Class,L}=runtime(classes,Request,{base_url:'/resources'}, {}, {});
 classes.baseclass=Class;classes.view=Class.extend({__init__(){starts++;}});
 return {L,starts:()=>starts};
}
(async()=>{
 // Reproduce the screenshot using LuCI's actual constructor check.
 const old=loader({'view.xray.lab_052':"'require view.xray.lab_148 as lab'; return lab;"});
 await assert.rejects(old.L.require('view.xray.lab_052'),/factory yields invalid constructor/);
 const menu=JSON.parse(fs.readFileSync(path.join(root,'../../../../usr/share/luci/menu.d/luci-app-forkop-xray.json'),'utf8'));
 const pages=Object.values(menu).filter(x=>x.action?.type==='view').map(x=>'view.'+x.action.path.replaceAll('/','.'));
 const legacy=['settings_052','settings_transfer2','dashboard_052','diagnostics_updates2','diagnostics_052','monitoring_compact_052'];
 for(const name of [...pages,...legacy.map(x=>'view.xray.'+x)]) {
  const test=loader(),page=await test.L.require(name);
  assert.equal(typeof page.render,'function',name);
  assert.equal(test.starts(),1,name+' must initialize exactly one view');
  assert.equal(await test.L.require(name),page,'Repeated load must reuse the instance');
  assert.equal(test.starts(),1);
 }
 const lab=loader(),helper=await lab.L.require('view.xray.lab_052');
 assert.equal(typeof helper.style,'function');assert.equal(typeof helper.status,'function');assert.equal(lab.starts(),0);
 for(const [old,current] of Object.entries({lab_052:'lab_148',settings_052:'settings_memory147',settings_transfer2:'settings_memory147',dashboard_052:'dashboard_148',diagnostics_updates2:'diagnostics_148',monitoring_compact_052:'monitoring_148'}))
  assert.equal(fs.readFileSync(path.join(root,'xray',old+'.js'),'utf8'),fs.readFileSync(path.join(root,'xray',current+'.js'),'utf8'),'Keep compatibility exports synchronized: '+old);
 console.log('Real LuCI loader: reproduced invalid constructor; all menu and legacy paths load with one view initialization');
})().catch(error=>{console.error(error);process.exit(1);});
