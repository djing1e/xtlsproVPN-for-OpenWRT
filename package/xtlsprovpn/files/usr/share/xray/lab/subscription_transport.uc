import * as fs from 'fs';
import { snapshot } from './state.mjs';
import { subscription_proxy } from './subscription_transport.mjs';
try {
    const runtime=json(fs.readfile('/var/etc/xray/config.json'));
    print(subscription_proxy(snapshot(),runtime));
} catch(e) { exit(0); }
