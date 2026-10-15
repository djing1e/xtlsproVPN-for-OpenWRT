// Bounded JSON serialization: do not build a second complete JSON string.
let fs = require('fs');
function write(path, value) {
    let file = fs.open(path, 'w', 0600);
    if (!file) die('Cannot open private JSON file');
    let parts = [];
    function flush() {
        if (!length(parts)) return;
        let text = join('', parts);
        if (file.write(text) != length(text)) die('Cannot write private JSON file');
        parts = [];
    }
    function emit(text) {
        push(parts, text);
        if (length(parts) >= 256) flush();
    }
    function encode(v) {
        let kind = type(v), first = true;
        if (kind == 'array') {
            emit('[');
            for (let item in v) {
                if (!first) emit(','); first = false;
                encode(item);
            }
            emit(']');
        } else if (kind == 'object') {
            emit('{');
            for (let key, item in v) {
                if (!first) emit(','); first = false;
                emit(sprintf('%J', key)); emit(':'); encode(item);
            }
            emit('}');
        } else emit(sprintf('%J', v));
    }
    try {
        encode(value); emit('\n'); flush();
        if (!file.close()) die('Cannot close private JSON file');
        if (!fs.chmod(path, 0600)) die('Cannot protect private JSON file');
    } catch (err) {
        file.close(); fs.unlink(path); die(err.message);
    }
}
return { write };
