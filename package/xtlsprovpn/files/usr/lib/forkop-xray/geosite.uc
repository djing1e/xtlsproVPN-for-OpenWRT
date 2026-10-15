// Xray v26.7.28 common/geodata/geodat.proto. Experimental, private candidates only.
// Preserve regex inline: Xray ignores malformed regex inside geosite assets,
// while inline config correctly rejects it. Never weaken that validation.
let fs = require('fs');
function varint(n) {
    let bytes = '';
    while (n >= 128) { bytes += sprintf('%c', (n & 127) | 128); n = n >> 7; }
    return bytes + sprintf('%c', n);
}
function field(n, data) { return varint(n * 8 + 2) + varint(length(data)) + data; }
function domain(entry) {
    let m = match(entry, /^(full|domain|keyword):(.+)$/);
    if (!m) return null;
    let kind = m[1] == 'full' ? 3 : m[1] == 'domain' ? 2 : 0;
    return sprintf('%c%c', 8, kind) + field(2, m[2]);
}
function same(a, b) {
    if (length(a) != length(b)) return false;
    for (let i, v in a) if (v != b[i]) return false;
    return true;
}
function compact(config, directory, threshold) {
    let file = fs.open(directory + '/lists.dat', 'w', 0600);
    if (!file) die('Cannot create private geosite asset');
    let known = [], parts = [], count = 0;
    function flush() {
        if (!length(parts)) return;
        let bytes = join('', parts);
        if (file.write(bytes) != length(bytes)) die('Cannot write geosite asset');
        parts = [];
    }
    function emit(bytes) { push(parts, bytes); if (length(parts) >= 256) flush(); }
    function pack(entries) {
        for (let item in known) if (same(item.entries, entries)) return item.tag;
        let tag = 'LIST' + length(known), header = field(1, tag), size = length(header);
        for (let entry in entries) size += length(field(2, domain(entry)));
        emit(varint(10) + varint(size) + header);
        for (let entry in entries) emit(field(2, domain(entry)));
        count += length(entries);
        push(known, {tag, entries});
        return tag;
    }
    function convert(rule, key) {
        if (type(rule) != 'object' || type(rule[key]) != 'array') return;
        let entries = [], inline = [];
        for (let entry in rule[key]) {
            if (type(entry) == 'string' && domain(entry) != null) push(entries, entry);
            else push(inline, entry);
        }
        if (length(entries) < (threshold || 64)) return;
        rule[key] = ['ext:lists.dat:' + pack(entries)];
        for (let entry in inline) push(rule[key], entry);
    }
    try {
        for (let rule in config.routing?.rules || []) convert(rule, 'domain');
        for (let server in config.dns?.servers || []) convert(server, 'domains');
        flush();
        if (!file.close()) die('Cannot close geosite asset');
    } catch (err) {
        file.close(); fs.unlink(directory + '/lists.dat'); die(err.message);
    }
    return {groups:length(known), entries:count};
}
return {compact};
