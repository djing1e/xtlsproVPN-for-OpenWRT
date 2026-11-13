import { snapshot, config, load, save, run_dir, uptime, capture, probe } from './state.mjs';
import { auto_run } from './auto_runtime.mjs';
const g=config().general || {}, s=snapshot();
function api(op,args) {
    const reply=capture(['timeout','-k','1','5','env','GOMEMLIMIT=24MiB','GOMAXPROCS=2',
        '/usr/libexec/forkop-xray/xray','api',op,'--server=127.0.0.1:8080','--timeout=2',...args]);
    if (!reply.ok) die('Xray API unavailable');
    return op=='bi'?json(reply.text):{};
}
const result=auto_run(s,g,load(run_dir+'/auto-selection.json') || {},uptime(),
    {api,probe:port=>probe(port,g.fx_probe_url || 'https://cp.cloudflare.com/generate_204',3)});
save(run_dir+'/auto-selection.json',result.state);
if (result.changed) print('changed');
