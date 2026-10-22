# Subscription download after a direct TLS handshake failure

The v1.4.2-r1 downloader retries DNS, TCP and timeout failures through the generic SOCKS listener. A TLS handshake failure (`curl=35`, HTTP 000) does not trigger that retry. The generic listener also follows user routing policy, so a subscription host can be sent DIRECT again.

This patch adds curl 35 to connection failures eligible for one proxy retry. Certificate validation remains enabled for HTTPS and redirects. Certificate failures, HTTP errors and authentication errors are not retried. A failed fallback reports both direct and proxy results without printing subscription URLs or credentials.

The native update transaction chooses a fresh healthy node from runtime status, preferring the selected node. It verifies the dedicated loopback SOCKS listener and its route to the matching VLESS outbound. It does not use the generic policy-controlled listener. If no healthy pinned listener is available, only the direct attempt is performed.

For existing v1.4.2-r1 installations, `scripts/fix-subscription-tls-v142.sh` installs exactly four verified files from a pinned source commit under the control action lock. It checks the original hashes and package version, retains backups, rejects modified or partially patched targets, and rolls back file replacement on failure. It does not restart Xray or edit DNS, subscription settings, HWID or the saved catalogue. After installation, run `xray-lab sync` to use the normal validated update transaction.

Tests cover retry policy, unchanged identity headers, strict certificate checks, private URL handling, preservation of both transport errors, pinned node selection, transaction rollback, installer guards and idempotence.

This hotfix does not change DNS recovery while the proxy is stopped. That is a separate known issue. A successful download still requires a usable transport and a valid subscription response.
