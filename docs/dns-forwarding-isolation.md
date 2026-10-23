# Default DNS forwarding isolation

On Dimarouternew, standalone DNS and TTL probes returned TTL 60. Applying the same settings failed only when checking the answer through dnsmasq on port 53. Its UCI configuration contained `server=1.1.1.1` and `noresolv=1`, while the generated application include added loopback forwarders. The same package on another router had no explicit global server and passed the TTL checks.

Adding `server=/#/127.0.0.1#10553` is not an exclusive upstream selection. The dnsmasq maintainer explains that /#/ is equivalent to an unqualified default server: https://lists.thekelleys.org.uk/pipermail/dnsmasq-discuss/2022q3/016519.html . Existing global servers can therefore compete with the application's default forwarding path.

`dns_forward.uc up` temporarily removes global UCI servers (including /#/ entries) and sets noresolv=1 before dnsmasq is restarted with the application's include. Named split DNS routes and unrelated DHCP settings remain intact. Per-instance mode affects only the selected dnsmasq sections. `down` restores previous values only while they still match the application's last write. The private atomic state file is saved before committing UCI, survives boot, and remains available for retry if restoring DHCP fails.

DNS application rollback restarts the previous Xray configuration, using the same lifecycle restoration and reacquisition. Proxy stop restores the direct DNS configuration. The TTL validation remains strict; an error now identifies the port, actual TTL and expected TTL.

Tests cover the observed explicit-server configuration, repeated activation and stop, absent options, split DNS, per-instance selection, administrator edits and failed UCI commits. Hardware confirmation on Dimarouternew remains required. This change does not establish the cause of Instagram failures or fix DNS application while Xray is stopped.

The code-only installer `scripts/fix-dns-forwarding-143.sh` requires an archive containing it as install.sh and the three corrected files under files/. It verifies payload and installed source hashes, refuses modified code, keeps a private backup, and does not restart services or change DHCP itself. After installation, repeat DNS apply in LuCI. The installed APK version remains 1.4.3-r1 until a package release is built.
