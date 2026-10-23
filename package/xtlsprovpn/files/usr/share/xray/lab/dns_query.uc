#!/usr/bin/ucode
"use strict";
import * as socket from 'socket';
import { frame, frame_length } from './dns_wire.mjs';
let port=int(ARGV[0]),strategy=ARGV[1],mode=ARGV[2] || 'udp';
let expected=ARGV[3]!=null?int(ARGV[3]):null;
let qtype=strategy=='ipv6'?28:1;
let query=chr(113,57,1,0,0,1,0,0,0,0,0,0,7)+'openwrt'+chr(3)+'org'+chr(0,0,qtype,0,1);
let s=socket.connect('127.0.0.1',port,{socktype:mode=='tcp'?socket.SOCK_STREAM:socket.SOCK_DGRAM},1000);
if (!s) die('DNS '+mode+' connect: '+(socket.error() || 'failed'));
let packet=mode=='tcp'?frame(query):query;
if (s.send(packet)!=length(packet)) die('DNS send failed');
let data='',complete=false,end=clock(true)[0]+12;
while (clock(true)[0]<end) {
    let event=socket.poll(1000,[s,socket.POLLIN]);
    if (!event) die('DNS poll: '+(socket.error() || 'failed'));
    let flags=event[0][1];
    if (!flags) continue;
    let part=s.recv(65537-length(data),socket.MSG_DONTWAIT);
    if (part==null) {
        let error=socket.error();
        if (!(flags & (socket.POLLERR|socket.POLLHUP|socket.POLLNVAL))) continue;
        die('DNS '+mode+' receive on '+port+': '+(error || 'socket error')+'; poll='+flags);
    }
    if (part=='') die('DNS '+mode+' closed connection on '+port);
    data+=part;
    if (mode!='tcp') {complete=true;break;}
    let size=frame_length(data);
    if (size!=null && length(data)>=size+2) {data=substr(data,2,size);complete=true;break;}
}
s.close();
if (!complete) die('DNS '+mode+' timeout on '+port);
if (length(data)<12 || substr(data,0,2)!=substr(query,0,2) || (ord(data,3)&15)!=0 || !(ord(data,6)|ord(data,7)))
    die('DNS returned no address');
// Xray emits one compressed name followed by an A/AAAA resource header.
let p=12;
while (p<length(data) && ord(data,p)) p+=ord(data,p)+1;
p+=5;
if ((ord(data,p)&192)==192) p+=2;
else {while(p<length(data) && ord(data,p))p+=ord(data,p)+1;p++;}
if (p+10>length(data)) die('Malformed DNS answer');
let ttl=(ord(data,p+4)<<24)|(ord(data,p+5)<<16)|(ord(data,p+6)<<8)|ord(data,p+7);
if (expected!=null && ttl!=expected) die('DNS '+mode+' on 127.0.0.1:'+port+': TTL '+ttl+', expected '+expected);
printf('%J\n',{ok:true,protocol:mode,ttl});
