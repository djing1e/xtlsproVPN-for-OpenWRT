"use strict";

import { cursor } from "uci";
import { load_options } from '../lab/dns_options.mjs';

export function load_config() {
    const uci = cursor(getenv("XRAY_UCI_CONFIG_DIR") || null);
    uci.load("xray_core");
    let config=uci.get_all("xray_core") || {};
    let options=load_options();
    if (options && config.general) {
        config.general._fx_dns=options;
        if (length(options.sources)) {
            config.general.lab_iface=options.sources[0];
            config.general.tproxy_ifaces_v4=options.sources;
        }
    }
    return config;
};
