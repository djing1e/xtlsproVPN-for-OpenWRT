"use strict";
function u16(s,p) { return (ord(s,p)<<8)|ord(s,p+1); }
export function frame(s) { return chr(length(s)>>8, length(s)&255)+s; };
export function frame_length(s) { return length(s)>=2?u16(s,0):null; };
function name_end(s,p) {
    for (let steps=0;steps<128;steps++) {
        if (p>=length(s)) return null;
        let n=ord(s,p++);
        if (!n) return p;
        if ((n&192)==192) return p<length(s)?p+1:null;
        if (n>63 || p+n>length(s)) return null;
        p+=n;
    }
    return null;
}
export function servfail(s) {
    if (length(s)<12) return null;
    return substr(s,0,2)+chr(128|(ord(s,2)&1),130)+substr(s,4,2)+chr(0,0,0,0,0,0)+substr(s,12);
};
export function rewrite_ttl(s,ttl) {
    if (length(s)<12 || !(ord(s,2)&128)) return null;
    let q=u16(s,4), records=u16(s,6)+u16(s,8)+u16(s,10), p=12, edits=[];
    if (q>32 || records>1024 || ttl<0 || ttl>86400) return null;
    for (let n=0;n<q;n++) {
        p=name_end(s,p);if (p==null || p+4>length(s)) return null;p+=4;
    }
    for (let n=0;n<records;n++) {
        p=name_end(s,p);if (p==null || p+10>length(s)) return null;
        let type=u16(s,p), size=u16(s,p+8);
        if (p+10+size>length(s)) return null;
        // OPT's TTL field contains EDNS flags, NOT a cache lifetime.
        if (type!=41) push(edits,p+4);
        p+=10+size;
    }
    let result='',start=0;
    const encoded=chr((ttl>>24)&255,(ttl>>16)&255,(ttl>>8)&255,ttl&255);
    for (let pos in edits) {result+=substr(s,start,pos-start)+encoded;start=pos+4;}
    return result+substr(s,start);
};
