// Only stable releases of this repository and an explicit platform manifest.
const REPO='djing1e/xtlsproVPN-for-OpenWRT';
export function version_ok(v) {
    return type(v)=='string' && length(v)<64 && match(v,/^[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+$/)!=null;
};
export function release_assets(r) {
    if (type(r)!='object' || r.draft!==false || r.prerelease!==false ||
        type(r.tag_name)!='string' || !match(r.tag_name,/^v[0-9]+\.[0-9]+\.[0-9]+$/) ||
        type(r.assets)!='array') die('Не найден совместимый стабильный релиз');
    let base='https://github.com/'+REPO+'/releases/download/'+r.tag_name+'/';
    let meta=filter(r.assets,a=>a.name=='update.json');
    if (length(meta)!=1 || meta[0].browser_download_url!=base+'update.json' ||
        !match(meta[0].digest || '',/^sha256:[a-f0-9]{64}$/) || meta[0].size<1 || meta[0].size>16384)
        die('В релизе отсутствует проверяемый манифест обновления');
    return {url:base+'update.json',sha256:substr(meta[0].digest,7),size:meta[0].size};
};
export function release_candidate(r) {
    if (type(r)!='object' || r.draft!==false || r.prerelease!==false ||
        !match(r.tag_name || '',/^v[0-9]+\.[0-9]+\.[0-9]+$/) || type(r.assets)!='array')
        die('Некорректный стабильный релиз');
    let apks=filter(r.assets,a=>match(a.name || '',/^xtlsprovpn-[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+\.apk$/));
    if (length(apks)!=1) die('Релиз должен содержать ровно один APK приложения');
    let a=apks[0],v=substr(a.name,11,length(a.name)-15);
    let url='https://github.com/'+REPO+'/releases/download/'+r.tag_name+'/'+a.name;
    if (!version_ok(v) || 'v'+split(v,'-r')[0]!=r.tag_name ||
        a.browser_download_url!=url || !match(a.digest || '',/^sha256:[a-f0-9]{64}$/) ||
        type(a.size)!='int' || a.size<1 || a.size>8388608) die('Некорректные данные APK');
    return {version:v,tag:r.tag_name,name:a.name,url,sha256:substr(a.digest,7),size:a.size,
        release_url:'https://github.com/'+REPO+'/releases/tag/'+r.tag_name};
};
export function release_plan(r,m,platform,arch) {
    release_candidate(r);
    release_assets(r);
    if (m?.schema!=1 || !version_ok(m.version) || m.tag!=r.tag_name ||
        'v'+split(m.version,'-r')[0]!=r.tag_name ||
        type(m.openwrt)!='array' || index(m.openwrt,platform)<0 ||
        type(m.architectures)!='array' || index(m.architectures,arch)<0 ||
        type(m.installed_size_kb)!='int' || m.installed_size_kb<1024 || m.installed_size_kb>32768)
        die('Манифест не подходит для версии OpenWrt или архитектуры роутера');
    let name='xtlsprovpn-'+m.version+'.apk';
    let assets=filter(r.assets,a=>a.name==name);
    if (length(assets)!=1 || m.apk?.name!=name ||
        !match(m.apk?.sha256 || '',/^[a-f0-9]{64}$/) ||
        assets[0].digest!='sha256:'+m.apk.sha256 ||
        type(m.apk.size)!='int' || m.apk.size<1 || m.apk.size>8388608 || assets[0].size!=m.apk.size)
        die('Контрольная сумма или размер APK не совпадают с данными GitHub');
    let url='https://github.com/'+REPO+'/releases/download/'+r.tag_name+'/'+name;
    if (assets[0].browser_download_url!=url) die('Недопустимый адрес APK');
    return {version:m.version,tag:r.tag_name,name,url,sha256:m.apk.sha256,size:m.apk.size,
        installed_size_kb:m.installed_size_kb,
        release_url:'https://github.com/'+REPO+'/releases/tag/'+r.tag_name};
};
