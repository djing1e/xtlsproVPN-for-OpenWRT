"use strict";

import { cursor } from "uci";
import { load_options } from '../lab/dns_options.mjs';
import { resolve_sources } from '../lab/source_interfaces.mjs';

export function load_config() {
    const uci = cursor(getenv("XRAY_UCI_CONFIG_DIR") || null);
    uci.load("xray_core");
    let config=uci.get_all("xray_core") || {};
    let options=load_options();
    if (config.general) {
        config.general._fx_dns=options;
        let sources=resolve_sources(options?.sources,config.general);
        if (length(sources)) {
            config.general.lab_iface=sources[0];
            config.general.tproxy_ifaces_v4=sources;
        }
    }
    return config;
};
