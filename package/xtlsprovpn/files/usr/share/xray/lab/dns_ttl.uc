#!/usr/bin/ucode
"use strict";
// Bounded loopback-only framing/TTL relay. TLS, caching and routing stay in Xray.
import * as socket from 'socket';
import { frame, frame_length, rewrite_ttl, servfail } from './dns_wire.mjs';
import * as fs from 'fs';
let ttl=int(ARGV[0]),port=int(ARGV[1] || 10553),upstream=int(ARGV[2] || 5300),ready=ARGV[3];
if (ttl<0 || ttl>86400 || (port!=0 && port<1024) || port>65535 || upstream<1024 || upstream>65535 || (port==0 && !ready)) die('Invalid TTL relay arguments');
const requested_port=port;
let udp,tcp,last_error;
for (let attempt=0;attempt<8;attempt++) {
    udp=socket.listen('127.0.0.1',requested_port,{socktype:socket.SOCK_DGRAM});
    if (!udp) die('TTL UDP bind on '+requested_port+': '+(socket.error() || 'failed'));
    port=udp.sockname().port;
    // TCP TIME_WAIT must not prevent a service restart. Never enable REUSEPORT.
    tcp=socket.listen('127.0.0.1',port,{socktype:socket.SOCK_STREAM},16,true);
    if (tcp) break;
    last_error=socket.error();udp.close();udp=null;
    if (requested_port!=0) break;
}
if (!udp || !tcp) die('TTL TCP bind on '+port+': '+(last_error || 'failed'));
if (ready) {
    if (!fs.writefile(ready,''+port+'\n')) die('Cannot report TTL relay port');
    fs.chmod(ready,0600);
}
let clients=[];
function now() { return clock(true)[0]; }
function close(c) {
    if (c.up) c.up.close();if (c.client) c.client.close();c.closed=true;
}
function send_result(c,answer) {
    if (c.up) {c.up.close();c.up=null;}
    if (!answer) answer=servfail(c.query || '');
    if (!answer) {close(c);return;}
    if (c.address) {udp.send(answer,0,c.address);close(c);}
    else c.output=frame(answer);
}
function begin(c,q) {
    c.query=q;
    c.up=socket.connect('127.0.0.1',upstream,{socktype:socket.SOCK_STREAM},100);
    if (!c.up) {send_result(c,null);return;}
    c.send=frame(q);c.receive='';
}
while (true) {
    let specs=[[udp,socket.POLLIN],[tcp,socket.POLLIN]];
    for (let c in clients) {
        if (c.closed) continue;
        if (c.client) push(specs,[c.client,c.output?socket.POLLOUT:(!c.up?socket.POLLIN:0)]);
        if (c.up) push(specs,[c.up,length(c.send)?socket.POLLOUT:socket.POLLIN]);
    }
    let events=socket.poll(200,...specs) || [];
    for (let event in events) {
        let fd=event[0],flags=event[1];if (!flags) continue;
        if (fd==udp && (flags&socket.POLLIN)) {
            let address={},q=udp.recv(65535,socket.MSG_DONTWAIT,address);
            if (!q || length(q)<12) continue;
            let c={address,created:now(),input:'',output:''};
            if (length(clients)>=32) {let failure=servfail(q);if(failure)udp.send(failure,0,address);continue;}
            push(clients,c);begin(c,q);continue;
        }
        if (fd==tcp && (flags&socket.POLLIN)) {
            let client=tcp.accept({},socket.SOCK_NONBLOCK|socket.SOCK_CLOEXEC);
            if (!client) continue;
            if (length(clients)>=32) {client.close();continue;}
            push(clients,{client,created:now(),input:'',output:''});continue;
        }
        let c=filter(clients,c=>!c.closed && (c.client==fd || c.up==fd))[0];
        if (!c) continue;
        if (fd==c.client) {
            if (flags&socket.POLLOUT) {
                let n=fd.send(c.output,socket.MSG_DONTWAIT);
                if (n==null || n<=0) close(c);
                else {c.output=substr(c.output,n);if (!length(c.output)) close(c);}
            } else if (flags&socket.POLLIN) {
                let data=fd.recv(65537-length(c.input),socket.MSG_DONTWAIT);
                if (data=='' || data==null) {close(c);continue;}
                c.input+=data;let n=frame_length(c.input);
                if (n!=null && (n<12 || n>65535)) {close(c);continue;}
                if (n!=null && length(c.input)>=n+2) begin(c,substr(c.input,2,n));
            } else if (flags&(socket.POLLHUP|socket.POLLERR|socket.POLLNVAL)) close(c);
        } else {
            if (flags&socket.POLLOUT) {
                let n=fd.send(c.send,socket.MSG_DONTWAIT);
                if (n==null || n<=0) {send_result(c,null);continue;}
                c.send=substr(c.send,n);
            }
            if (!c.closed && c.up && (flags&socket.POLLIN)) {
                let data=fd.recv(65537-length(c.receive),socket.MSG_DONTWAIT);
                if (data==null || data=='') {send_result(c,null);continue;}
                c.receive+=data;let n=frame_length(c.receive);
                if (n!=null && n<12) {send_result(c,null);continue;}
                if (n!=null && length(c.receive)>=n+2) {
                    let answer=substr(c.receive,2,n);
                    if (substr(answer,0,2)!=substr(c.query,0,2)) send_result(c,null);
                    else send_result(c,rewrite_ttl(answer,ttl));
                }
            } else if (!c.closed && c.up && (flags&(socket.POLLHUP|socket.POLLERR|socket.POLLNVAL))) send_result(c,null);
        }
    }
    for (let c in clients) if (!c.closed && now()-c.created>10) close(c);
    clients=filter(clients,c=>!c.closed);
}
