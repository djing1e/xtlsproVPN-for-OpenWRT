"use strict";
import * as fs from 'fs';

function valid(name) {
    return type(name)=='string' && name!='lo' && match(name,/^[A-Za-z0-9_.-]{1,15}$/)!=null;
}
// Only the client LAN is an automatic source. Never infer it from the default
// route: in an access-point setup that route can use the same LAN bridge.
export function resolve_sources(explicit, general) {
    if (length(explicit || [])) return explicit;
    let lan;
    const fixture=getenv('XRAY_LAB_NETWORK_JSON');
    try {
        if (fixture) lan=json(fs.readfile(fixture));
        else {
            const proc=fs.popen('ubus call network.interface.lan status 2>/dev/null','r');
            if (proc) {
                const body=proc.read('all'),code=proc.close();
                if (code==0) lan=json(body);
            }
        }
    } catch (e) {}
    const device=lan?.l3_device || lan?.device;
    if (lan?.up && valid(device)) return [device];
    // Keep the saved profile usable while netifd is starting or unavailable.
    if (valid(general?.lab_iface)) return [general.lab_iface];
    die('Не удалось определить интерфейс источника LAN. Выберите его в «DNS и сеть».');
};
