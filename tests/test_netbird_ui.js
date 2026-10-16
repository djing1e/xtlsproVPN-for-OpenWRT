'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,
    '../package/xtlsprovpn/files/www/luci-static/resources/view/xray/netbird.js'), 'utf8');

function E(tag, attrs = {}, children = []) {
    return {tag, attrs, children: Array.isArray(children) ? children : [children],
        style: {}, value: attrs.value || '', disabled: false, textContent: '',
        checkValidity() { return this.value.startsWith('https://'); }};
}
function all(node) {
    return typeof node === 'object' && node ?
        [node, ...node.children.flatMap(all)] : [];
}
async function main() {
    let data = {installed: true, connected: false, enabled: false, job: {state:'idle'},
        resources: {binary_bytes: 10485760, rss_bytes: 0}};
    const calls = [];
    let poller;
    const rpc = {declare(spec) {
        return spec.method === 'status' ? async () => data : async (...args) => {
            calls.push(args);
            data = {...data, job: {state:'running',message:'Подключение'}};
            return {ok:true};
        };
    }};
    const view = new Function('baseclass','rpc','poll','E',source)(
        {extend:x => x}, rpc, {add:fn => {poller=fn;}}, E);
    const page = await view.render();
    const nodes = all(page);
    const url = nodes.find(n => n.attrs['aria-label'] === 'Сервер управления NetBird');
    const key = nodes.find(n => n.attrs['aria-label'] === 'Setup key NetBird');
    const connect = nodes.find(n => n.tag === 'button' && n.children[0] === 'Подключить / применить');
    const install = nodes.find(n => n.tag === 'button' && n.children[0] === 'Установить NetBird');
    assert.equal(install.disabled, true);
    assert.equal(connect.disabled, false);
    url.value='https://nb.example.test';key.value='11111111-2222-4333-8444-555555555555';
    connect.attrs.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls[0][0], 'connect');
    assert.equal(calls[0][1], url.value);
    assert.equal(calls[0][3], '11111111-2222-4333-8444-555555555555');
    assert.equal(key.value, '');
    assert.equal(connect.disabled, true);
    data = {...data, connected:true, netbird_ip:'100.100.0.5/16',
        job:{state:'done',message:'Подключён'}};
    await poller();
    assert.equal(connect.disabled, false);
    assert(nodes.some(n => n.textContent.includes('100.100.0.5/16')));
    console.log('NetBird UI: render, submit, secret clearing, busy state and polling passed');
}
main().catch(e => {console.error(e);process.exit(1);});
