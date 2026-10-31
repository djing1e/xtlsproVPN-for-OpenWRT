const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync('package/xtlsprovpn/files/www/luci-static/resources/view/xray/lab_148.js','utf8');
function E(tag,attrs={},children=[]) {
    return {tag,attrs,children:Array.isArray(children)?children:[children],isConnected:false,
        appendChild(n){this.children.push(n);n.parent=this;n.isConnected=true;},
        get firstChild(){return this.children[0];},
        remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.isConnected=false;}};
}
async function main(){
    let data={job:{state:'idle'},operation_busy:false},response={id:'one'},body=E('body');
    const rpc={declare:spec=>spec.method==='action'?async()=>response:async()=>data};
    const lab=new Function('baseclass','rpc','ui','E','document','setTimeout',source)(
        {extend:x=>x},rpc,{},E,{body},()=>0);
    assert.equal(lab.reason('direct_mode'),'Прямой интернет — ожидаем восстановления прокси');
    assert.equal(lab.reason('recover'),'Восстановление прокси');
    assert(lab.jobNote({job:{state:'running',action:'bypass'}}).children[0].includes('Переход на прямой интернет'));
    data={job:{id:'one',state:'failed',action:'sync',message:'Недостаточно RAM'},operation_busy:false};
    await lab.request('sync','','',{});assert.equal(lab.busy(data),false);
    assert(body.children[0].children.some(n=>JSON.stringify(n.children.map(x=>x.tag==='div'?x.children.map(y=>y.children):[])).includes('Недостаточно RAM')));
    response={id:'two'};data={job:{id:'two',state:'running'},operation_busy:true};
    await lab.request('sync','','',{});assert.equal(lab.busy(data),true);
    data={job:{id:'recovery',state:'running'},operation_busy:true};await lab.status();assert.equal(lab.busy(data),true);
    data={job:{id:'recovery',state:'done'},operation_busy:false};await lab.status();assert.equal(lab.busy(data),false);
    response={};await lab.request('sync','','',{});assert.equal(lab.busy(data),false);
    console.log('Dashboard jobs: failure details, completed failure, replaced job and missing RPC ID unlock controls');
}
main().catch(e=>{console.error(e);process.exit(1);});
