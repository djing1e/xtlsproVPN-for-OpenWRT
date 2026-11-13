# FinalMask subscription import for 1.4.8-r1

Remnawave emits the FinalMask object as JSON in the `fm` VLESS URI parameter.
The native importer previously rejected that query parameter. For Xray JSON
subscriptions, rebuilding streamSettings also discarded finalmask, so variants
of one endpoint could collapse into the same node identity.

The parser now preserves FinalMask for RAW/REALITY and XHTTP. It accepts URI `fm`
(and the explicit finalmask/finalMask aliases), and streamSettings.finalmask or
finalMask in JSON, emitting the canonical Xray spelling `finalmask`. Duplicate
aliases, malformed JSON, wrong shapes, oversized objects, excessive nesting and
unknown envelope fields are rejected with fixed messages that do not echo URIs
or mask secrets. Native Xray remains responsible for mask-specific compatibility
and configuration validation before a subscription is committed.

Mask contents are part of masked endpoint identity, preventing collisions between
masked/unmasked variants sharing address, port and UUID. Sorting object keys
makes equivalent mask objects deduplicate consistently. Array order is preserved.
Identities of nodes without a mask are unchanged.

Tests cover Remnawave-style URIs, base64 subscription envelopes, JSON case aliases,
encoded plus signs, malformed/ambiguous inputs, identity behavior, and the actual
URI → catalogue → native generator → Xray 26.7.28 validation pipeline for both
supported transport families. This validates configuration preservation and core
acceptance; the provider's actual mask settings still need an on-router check.

Sources:
- https://github.com/remnawave/backend/blob/main/src/modules/subscription-template/generators/xray.generator.service.ts
- https://github.com/XTLS/Xray-core/blob/v26.7.28/infra/conf/transport_finalmask.go
