#!/usr/bin/ucode
let fs=require('fs');
let op=ARGV[0];

if (op=='check') exit(0);


if (op=='release-catalog') {
    let entries={};
    for (let n=1;n<length(ARGV);n++) {
        let source=json(fs.readfile(ARGV[n]) || 'null');
        let releases=type(source)=='array'?source:[source];
        for (let r in releases) {
            if (type(r)!='object' || r.draft!==false ||
                (r.prerelease!==false && !(getenv('FX_CORE_ALLOW_PRERELEASE')=='1' && r.prerelease===true)) ||
                !match(r.tag_name || '',/^v[0-9]{1,3}\.[0-9]{1,2}\.[0-9]{1,2}$/))
                continue;
            let name='Xray-linux-arm64-v8a.zip';
            let url='https://github.com/XTLS/Xray-core/releases/download/'+r.tag_name+'/'+name;
            let asset=filter(r.assets || [],a=>a.name==name &&
                a.browser_download_url==url)[0];
            let digest=filter(r.assets || [],a=>a.name==name+'.dgst' &&
                a.browser_download_url==url+'.dgst')[0];
            if (!asset || !digest || asset.size<=0 || asset.size>67108864)
                continue;
            let version=substr(r.tag_name,1);
            entries[version]={version,published:r.published_at,size:asset.size,prerelease:r.prerelease};
        }
    }
    let versions=sort(keys(entries),(a,b)=>{
        let x=split(a,'.'),y=split(b,'.');
        for (let n=0;n<3;n++) {
            let delta=int(y[n])-int(x[n]);
            if (delta) return delta;
        }
        return 0;
    });
    if (!length(versions))
        die('ARM64-релизы не найдены или скрыты фильтром');
    let path=getenv('FX_CORE_CATALOG_FILE');
    if (path) {
        if (!fs.writefile(path+'.new',sprintf('%J\n',{
            checked:time(),releases:map(versions,v=>entries[v])
        }))) die('Не удалось записать каталог');
        fs.chmod(path+'.new',0600);
        if (!fs.rename(path+'.new',path)) die('Не удалось сохранить каталог');
    }
    for (let version in versions) print(version+'\n');
    exit(0);
}

if (op=='ports') {
    let c=json(fs.readfile('/var/etc/xray/config.json') || '{}');
    for (let i in c.inbounds || []) {
        if (i.listen!='127.0.0.1' || i.protocol!='socks' ||
            !match(i.tag || '',/^fx_probe:cfg[A-Za-z0-9_-]{6}$/) ||
            type(i.port)!='int' || i.port<1024 || i.port>65535)
            continue;
        let rules=filter(c.routing?.rules || [],r=>
            length(r.inboundTag || [])==1 &&
            r.inboundTag[0]==i.tag &&
            r.outboundTag=='fx_node:'+substr(i.tag,9));
        if (length(rules)) printf('%d\n',i.port);
    }
    exit(0);
}


if (op=='release') {
    let releases=json(fs.readfile(ARGV[1]) || 'null');
    let channel=getenv('FX_CORE_CHANNEL') || 'latest';
    if (type(releases)!='array')
        die('Expected official release list');
    if (index(['latest','stable'],channel)<0)
        die('Invalid release channel');

    function compare(a,b) {
        let x=split(substr(a,1),'.');
        let y=split(substr(b,1),'.');
        for (let n=0;n<3;n++) {
            let delta=int(x[n])-int(y[n]);
            if (delta) return delta;
        }
        return 0;
    }

    let best=null;
    for (let r in releases) {
        if (r.draft!==false ||
            (r.prerelease!==true && r.prerelease!==false) ||
            (channel=='stable' && r.prerelease!==false) ||
            !match(r.tag_name || '',/^v[0-9]{1,3}\.[0-9]{1,2}\.[0-9]{1,2}$/))
            continue;

        let name='Xray-linux-arm64-v8a.zip';
        let url='https://github.com/XTLS/Xray-core/releases/download/'+r.tag_name+'/'+name;
        let asset=filter(r.assets || [],a=>a.name==name &&
            a.browser_download_url==url)[0];
        let digest=filter(r.assets || [],a=>a.name==name+'.dgst' &&
            a.browser_download_url==url+'.dgst')[0];

        if (!asset || !digest || asset.size<=0 || asset.size>67108864)
            continue;
        if (!best || compare(r.tag_name,best.tag_name)>0)
            best=r;
    }

    if (!best)
        die('No suitable ARM64 release in the selected channel');

    print(substr(best.tag_name,1));
    exit(0);
}

if (op=='checksum') {
    let body=fs.readfile(ARGV[1]) || '';
    let m=match(body,/SHA(2-)?256[[:space:]]*=[[:space:]]*([a-fA-F0-9]{64})([[:space:]]|$)/);
    if (!m) die('Official SHA256 digest not found');
    print(m[2]);
    exit(0);
}

if (op=='newer') {
    let a=split(ARGV[1],'.'), b=split(ARGV[2],'.');
    if (length(a)!=3 || length(b)!=3) die('Invalid version');
    for (let n=0;n<3;n++) {
        if (int(a[n])>int(b[n])) exit(0);
        if (int(a[n])<int(b[n])) exit(1);
    }
    exit(1);
}

if (op=='record') {
    let path='/var/run/xray-lab-control/core-update.json';
    let old={};
    try { old=json(fs.readfile(path) || '{}'); } catch(e) {}
    let data={
        action:ARGV[1],channel:getenv('FX_CORE_CHANNEL') || 'latest',
        phase:ARGV[2],
        message:ARGV[3],
        installed:ARGV[4],
        available:ARGV[5] || old.available || null,
        updated:time()
    };
    if (!fs.writefile(path+'.new',sprintf('%J\n',data)))
        die('Cannot write updater state');
    fs.chmod(path+'.new',0600);
    if (!fs.rename(path+'.new',path))
        die('Cannot commit updater state');
    exit(0);
}

die('Unknown helper operation');
