const fs=require('fs');
const assert=require('assert');
const source=fs.readFileSync(__dirname+'/../package/xtlsprovpn/files/www/luci-static/resources/view/xray/core_update_transfer2.js','utf8');
function E(tag,attrs,children){return {tag,attrs:attrs||{},children:children||[],replaceChildren(...v){this.children=v;}};}
async function check(progress,expected){
 const data={installed:'26.10.10',pinned_version:'26.9.9',include_prerelease:true,catalog:{releases:[{version:'26.9.9',prerelease:true}]},job:{state:'running',started:100},update:{phase:'download',available:'26.9.9'},progress};
 const component=new Function('baseclass','rpc','poll','E',source)({extend:x=>x},{declare:()=>()=>Promise.resolve(data)},{add:()=>{}},E);
 const tree=await component.render();let bars=[];
 function walk(n){if(Array.isArray(n))n.forEach(walk);else if(n&&typeof n==='object'){if(n.attrs?.role==='progressbar')bars.push(n);walk(n.children);}}
 walk(tree);assert.equal(bars.length,1);assert.equal(bars[0].attrs['aria-valuenow'],expected);
}
(async()=>{await check({},undefined);await check({version:'26.9.9',received:50,total:100,started:100,updated:101},'50');await check({version:'26.7.28',received:100,total:100,started:90,updated:99},undefined);console.log('Transfer UI: bar remains visible with missing or stale counters; 50% renders correctly');})().catch(e=>{console.error(e);process.exit(1)});
