"""Cold UI installation must fail before publishing a core or touching networking."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'package/xtlsprovpn/files'


class FirstCoreFailure(unittest.TestCase):
    def test_cold_ui_failures(self):
        scenarios = ('metadata', 'download', 'digest_download', 'checksum',
                     'archive', 'extract', 'truncated', 'version', 'config',
                     'space', 'copy')
        for action in ('test', 'install'):
            for scenario in scenarios:
                if action == 'test' and scenario in ('space', 'copy'):
                    continue
                with self.subTest(action=action, scenario=scenario), tempfile.TemporaryDirectory() as temp:
                    d = Path(temp)
                    tools = d / 'tools'
                    tools.mkdir()
                    binary = d / 'lib/xray'
                    binary.parent.mkdir()
                    run = d / 'run'

                    def tool(name, body):
                        p = tools / name
                        p.write_text('#!/bin/sh\n' + body)
                        p.chmod(0o755)

                    candidate = ('#!/bin/sh\nif [ "$1" = version ]; then echo "Xray ' +
                                 ('0.0.0' if scenario == 'version' else '26.7.28') +
                                 '"; else exit ' + ('1' if scenario == 'config' else '0') + '; fi\n')
                    (d / 'candidate').write_text(candidate)
                    tool('uname', 'echo aarch64\n')
                    tool('uci', 'case "$*" in "-q get xray_core.general.xray_bin") echo "' +
                         str(binary) + '";; "-q get xray_lab_core.main.include_prerelease") :;; *) echo uci >> "' +
                         str(d / 'mutated') + '"; exit 1;; esac\n')
                    tool('curl', 'out=\nwhile [ "$#" -gt 0 ]; do\n'
                         'if [ "$1" = --output ]; then shift; out=$1; fi\nshift\ndone\n' +
                         ('case "$out" in */selected.json) exit 28;; esac\n' if scenario == 'metadata' else '') +
                         ('case "$out" in */core.zip) printf partial > "$out"; exit 28;; esac\n' if scenario == 'download' else '') +
                         ('case "$out" in */core.dgst) exit 28;; esac\n' if scenario == 'digest_download' else '') +
                         'printf zip > "$out"\n')
                    digest = hashlib.sha256(b'zip').hexdigest()
                    tool('ucode', 'case "$2" in\nrelease-catalog) echo 26.7.28;;\n'
                         'checksum) echo ' + ('bad' if scenario == 'checksum' else digest) + ';;\n'
                         'record) printf "%s\n" "$*" >> "' + str(d / 'records') + '";;\n'
                         'asset-size) echo 3;;\nports|progress) :;;\n*) exit 1;;\nesac\n')
                    size = len(candidate.encode())
                    tool('unzip', 'if [ "$1" = -l ]; then\n' +
                         ('echo "unexpected archive"' if scenario == 'archive' else 'echo "' + str(size) + ' xray"') +
                         '\nelse\n' + ('exit 1' if scenario == 'extract' else
                                         'printf short' if scenario == 'truncated' else
                                         'cat "' + str(d / 'candidate') + '"') + '\nfi\n')
                    tool('df', 'printf "Filesystem blocks used available cap mount\nfs 999999 0 ' +
                         ('0' if scenario == 'space' else '999999') + ' 0 /overlay\n"\n')
                    if scenario == 'copy':
                        tool('cp', 'touch "$2"; exit 1\n')
                    for name in ('ip', 'nft', 'ubus', 'service'):
                        tool(name, 'echo ' + name + ' >> "' + str(d / 'mutated') + '"; exit 1\n')
                    source = (ROOT / 'usr/bin/xray-lab-core').read_text()
                    source = source.replace('BIN=/usr/libexec/forkop-xray/xray', 'BIN=' + str(binary))
                    source = source.replace('RUN=/var/run/xray-lab-control', 'RUN=' + str(run))
                    source = source.replace('/etc/init.d/xray_core', str(tools / 'service'))
                    source = source.replace('/proc/meminfo', str(d / 'meminfo'))
                    (d / 'meminfo').write_text('MemAvailable: 200000 kB\n')
                    script = d / 'command'
                    script.write_text(source)
                    result = subprocess.run(['sh', str(script), action, '26.7.28'],
                                            env={**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH']},
                                            capture_output=True, text=True, timeout=15)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertFalse(binary.exists())
                    self.assertFalse(Path(str(binary) + '.next').exists())
                    self.assertFalse(Path(str(binary) + '.previous').exists())
                    self.assertFalse((d / 'mutated').exists())
                    records = (d / 'records').read_text()
                    self.assertIn('Настройки DNS и маршрутов не менялись.', records)
                    self.assertNotIn('Кандидат сохранён', records)


if __name__ == '__main__':
    unittest.main()
