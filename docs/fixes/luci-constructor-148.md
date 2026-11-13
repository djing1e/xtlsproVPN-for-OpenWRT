# LuCI Settings hotfix for 1.4.8-r1

The LuCI module loader instantiates dependencies and requires each module factory
to return a class constructor. The legacy `lab_052` shim returned the already
instantiated `lab_148` helper, so Settings failed with `factory yields invalid
constructor`. Other legacy view shims had the same export error.

Settings now imports `lab_148` directly. Legacy paths contain the canonical module
implementation rather than importing an instantiated helper or view. This avoids
both invalid exports and duplicate view initialization. The loader regression
test checks all menu and legacy paths using the class system and module loader
from LuCI 128a781; it also requires compatibility copies to stay synchronized.

`scripts/fix-luci-constructor-148.sh` applies the reviewed UI files to 1.4.8-r1.
It checks existing and downloaded SHA-256 values before installation, backs up
all replaced files, and restores them if a write fails. Unknown local changes or
other package versions are rejected before writing. A second run is a no-op.
No services, UCI settings, DNS, firewall or subscription data are changed.
Reload the browser with Ctrl+F5 after installation.
