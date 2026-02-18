# KOI Alignment: Octo vs BlockScience KOI-net

Last updated: 2026-02-18

> **Detailed tracking:** See [`koi-protocol-alignment-master.md`](./koi-protocol-alignment-master.md) for the full master reference document with test coverage matrix, file references, and phase validation criteria.

## Purpose

This document compares Octo's current KOI-net implementation with the BlockScience KOI-net and RID reference behavior, then proposes a minimal-risk path to align while keeping Octo operational.

## Executive Summary

Octo is interoperable with peer nodes (Regen, Cowichan Valley) and aligned with BlockScience KOI-net semantics on all high-impact areas. The remaining gaps are medium/low severity (handler chain pipeline, conformance test expansion, protocol surface documentation).

**Resolved (P0–P1):**

1. **Identity derivation** — Node RIDs migrated to `b64_64` (BlockScience canonical `sha256(base64(DER(pubkey)))`, 64 hex chars). Legacy 16-char RIDs still accepted during migration.
2. **Security policy** — Strict mode available: signed envelope requirement, `target_node == self` enforcement, sender key-RID binding checks. Unsigned fallback controlled by `KOI_STRICT_MODE` flag.
3. **Manifest hashing** — JCS-canonical via `rid-lib` hard dependency (no fallback). 3 conformance tests with frozen reference vector.
4. **Bootstrap** — Unknown node self-introduction via FORGET+NEW broadcast with key-RID binding verification.
5. **Error schema** — BlockScience `ErrorType` mapping with safe fallback (pre-auth errors don't trigger handshake retries).
6. **POLL edge enforcement** — Unapproved peers receive empty event lists.

**Resolved (P2):**

7. **Conformance tests** — 14 offline + 5 live tests using `koi-net` 1.2.4 as oracle. Wire format roundtrip, signed envelope cross-verification (both directions), node identity cross-verification, and live endpoint validation all pass.

**Resolved (P3–P4):**

8. **Handler chain pipeline** — 5-phase pipeline (`api/pipeline/`) with 7 handlers including `block_self_referential` (BlockScience `basic_rid_handler` parity) and `entity_type_validator`. Feature-flagged via `KOI_USE_PIPELINE=true`, deployed to production.
9. **Protocol surface cleanup** — Health endpoint reports `pipeline_enabled` from runtime state. Core vs extension endpoints documented. All Definition of Done criteria met.

## Reference Baseline (BlockScience)

The BlockScience KOI-net reference protocol defines five core endpoints under `/koi-net`:

- `POST /events/broadcast`
- `POST /events/poll`
- `POST /rids/fetch`
- `POST /manifests/fetch`
- `POST /bundles/fetch`

The reference server wraps protocol endpoints with envelope validation and enforces:

- sender can be resolved (or provided via bootstrap event pattern),
- sender public key matches sender node RID hash semantics,
- envelope signature verification,
- `target_node == self`.

The RID layer treats RIDs as references (not the resource itself), with manifests (`rid`, `timestamp`, `sha256_hash`) and canonicalized hashing via JCS.

## Current Octo Behavior

Octo currently implements:

- the 5 core endpoints,
- plus extensions: `POST /handshake`, `POST /events/confirm`, and `GET /health`.

Operationally useful behaviors include:

- poll edge semantics (`source = provider`, `target = poller`),
- automatic peer key refresh from `/koi-net/health`,
- handshake retry/self-healing when a poll fails due to missing peer key.

Main differences from strict reference behavior:

- unsigned fallback is accepted when request is not a signed envelope,
- no explicit router-level `target_node == self` check after envelope verification,
- node RID derivation uses a truncated hash suffix,
- manifest/bundle state response path is backed by Octo event tables and cross-ref workflow rather than the full reference cache/effector pipeline.

## Gap Matrix

> **Note:** The Priority column ranks gaps by *alignment impact severity* (how far from reference behavior). The implementation phases below are ordered by *implementation safety* — some high-severity gaps (like Node RID derivation) are deferred to later phases because they require migration coordination.

| Area | BlockScience expectation | Octo today | Alignment impact | Priority |
|---|---|---|---|---|
| Core endpoint set | 5 protocol endpoints | 5 + `handshake` + `confirm` + `health` | Low (extensions are fine) | P3 |
| Signed envelope requirement | Strict envelope handling on protocol endpoints | Signed preferred; unsigned fallback accepted | High (security + interop profile drift) | P0 |
| Envelope target validation | Reject if `target_node != self` | Not enforced at router boundary | High (replay/misroute risk) | P0 |
| Sender key ↔ RID binding | Validate node RID hash against sender public key | Signature checked, but no equivalent strict RID-hash binding check¹ | High (identity integrity gap) | P0 |
| Node RID derivation | Full SHA256 hex digest of base64(DER(pubkey)) (64 chars) | **b64_64 mode added (BlockScience canonical)**; legacy16 still accepted during migration | ~~High~~ → Resolved | P0 ✅ |
| Manifest canonical hashing | RID manifest/hash semantics with JCS | **rid-lib hard dependency**: `_canonical_sha256_json()` delegates to `rid_sha256_hash_json()`, no fallback. 3 JCS conformance tests with frozen reference vector | ~~Medium~~ → Resolved | P1 ✅ |
| Unknown-node bootstrap | Protocol-level unknown-node handling with handshake behavior | **Broadcast bootstrap implemented**: unknown nodes self-introduce via NEW event with NodeProfile; key-RID binding verified before trust | ~~Medium~~ → Resolved | P0 ✅ |
| Error response schema | `ErrorResponse(type="error_response", error=ErrorType)` | **Implemented**: all protocol errors include `type: "error_response"` + BlockScience `ErrorType` mapping | ~~High~~ → Resolved | P0 ✅ |
| POLL edge enforcement | Unapproved peers get empty results | **Implemented**: `KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL` (auto-enabled with strict mode) | ~~Medium~~ → Resolved | P1 ✅ |
| State sync architecture | Reference cache/effector/handler pipeline | Event queue + cross-reference resolver pipeline | Medium (interop model variance) | P2 |
| Provenance model | Manifest-centric and broader CAT/provenance direction | Delivery/confirm tracking + cross-refs; limited cryptographic provenance trail | Medium | P2 |

¹ The reference (`secure.py`) validates that the hash suffix of the source node RID matches `sha256_hash(public_key.to_der())`, proving the sender controls the key embedded in their identity.
² Severity is high, but implementation is deferred to Phase P2 due to migration complexity and peer coordination requirements.

## Alignment Plan (Elegant, Low-Disruption)

## Execution Status (2026-02-17)

- P0 implemented in Octo:
  - strict-mode policy flags (`KOI_STRICT_MODE` + fine-grained toggles),
  - unsigned-envelope rejection controls (handshake exception preserved),
  - explicit envelope `target_node` enforcement,
  - sender RID/public-key binding checks,
  - **error response schema**: all protocol errors include `type: "error_response"` + BlockScience `ErrorType` mapping (`unknown_node`, `invalid_key`, `invalid_signature`, `invalid_target`),
  - **node RID `b64_64` mode**: `sha256(base64(DER(pubkey)))` full 64-char hex — matches BlockScience `sha256_hash(pub_key.to_der())` exactly. Default for new nodes. Legacy16 still accepted during migration via `KOI_ALLOW_LEGACY16_NODE_RID=true`,
  - **broadcast bootstrap**: unknown nodes can self-introduce via `/events/broadcast` with a `NEW` event carrying `NodeProfile` + `public_key`. Key-RID binding is verified before trusting the new peer,
  - **POLL edge enforcement**: `KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL` (auto-enabled with strict mode) returns empty events for unapproved peers.
- P1 **complete**:
  - `rid-lib` is now a hard runtime dependency — `from rid_lib.ext.utils import sha256_hash_json` (no fallback path).
  - `_canonical_sha256_json()` delegates to `rid_sha256_hash_json()` for all manifest hashing.
  - 3 JCS conformance tests: float handling (`1.0` → `1`), frozen reference vector from rid-lib 3.2.14, key-order determinism.
- P2 **complete**:
  - `test_koi_conformance.py`: 14 offline tests + 5 live tests (19 total) using `koi-net` 1.2.4 as oracle.
  - Wire format byte-identical between Octo and koi-net for signing input.
  - Signed envelope cross-verification passes both directions.
  - Dedicated `venv-conformance/` avoids resolver conflicts (koi-net requires fastapi>=0.115, Octo pins 0.104).
  - Handler chain pipeline (5-phase: RID → Manifest → Bundle → Network → Final) — now P3.
- P3 **complete**:
  - 5-phase handler chain pipeline with 7 handlers (4 RID, 2 Bundle, 1 Final), feature-flagged via `KOI_USE_PIPELINE=true`.
  - P3b new handlers: `block_self_referential` (BlockScience `basic_rid_handler` parity), `entity_type_validator` (debug logging for unknown types).
  - 26 pipeline tests passing.
- P4 **complete**:
  - `pipeline_enabled` field in health endpoint (runtime state, not env var).
  - Core vs extension endpoint boundaries documented in health metadata and master doc.
  - All 5 Definition of Done criteria met.

### Phase P0: Interop/Security Hardening (no architecture rewrite)

1. Add `KOI_STRICT_MODE` (default `false` initially):
   - when `true`, require signed envelopes for protocol endpoints (except the `/koi-net/handshake` endpoint, which by design accepts unsigned payloads for initial key exchange),
   - reject unsigned fallback requests.
2. Enforce explicit `target_node == self` on all signed requests.
3. Enforce sender key to sender RID binding at validation time.
4. Standardize KOI protocol error responses for signature/key/target failures.
5. Coordinate strict-mode rollout across all active federation peers. Deploy envelope-signing to peers before enabling `KOI_STRICT_MODE=true` on Octo.

### Phase P1: RID and Manifest Canonicalization

1. Use `rid-lib` directly for manifest/hash operations and RID helper paths.
2. Remove duplicated ad-hoc hash derivations in KOI wire paths where `rid-lib` primitives should be authoritative.
3. Add conformance tests:
   - outgoing manifests hash equivalence with `rid-lib` canonical output,
   - envelope + RID/key binding validation vectors.

### Phase P2: Node Identity Migration Strategy

1. Introduce a compatibility migration for node IDs:
   - keep current RIDs readable,
   - add canonical RID support (and alias mapping),
   - migrate peers gradually without breaking active federations.
2. Do not "flip all IDs at once." Use dual-accept and phased cutover.

### Phase P3: Protocol Surface and Packaging Cleanup

1. Keep `handshake`, `confirm`, and `health` as pragmatic Octo extensions, but document them as extensions (not baseline KOI core).
2. Separate "core KOI protocol compliance" from "Octo federation conveniences" in docs and tests.

## PyPI Package Adoption Guidance

As of 2026-02-12, PyPI lists:

- `koi-net` latest stable release: `1.2.4` (latest pre-release: `1.3.0b8`; requires Python `>=3.10`)
- `rid-lib` latest release: `3.2.14` (requires Python `>=3.10`)

### `rid-lib` (recommended now)

Adopt more deeply immediately. It is already in dependencies (`>=3.2.8`), but runtime KOI identity/hash behavior is still partly custom. Current floor `>=3.2.8` is acceptable; pin to a specific minor version only if a breaking change is encountered.

Recommended first uses:

- canonical manifest generation and hash checks,
- RID utility normalization in KOI protocol paths,
- test fixtures generated from `rid-lib` objects.

### `koi-net` (recommended as staged adoption, not immediate replacement)

Not currently in Octo's runtime dependencies (only `rid-lib` is). Use a dedicated conformance test environment (`requirements-conformance.txt`) for `koi-net` contract testing to avoid resolver conflicts with Octo runtime pins.

The package is highly relevant and should be used where practical, but Octo has a different runtime architecture (DB-backed event queues, cross-ref projection, custom lifecycle and extensions). A full drop-in replacement today would be a risky rewrite.

Best near-term path:

1. Use `koi-net` as a **reference conformance oracle** (contract tests + behavior diffs).
2. Extract reusable pieces incrementally where integration cost is low.
3. Re-evaluate full router/poller replacement after strict-mode and RID migration are complete.

## Definition of Done for "Aligned Enough"

The system is considered aligned for production federation when all are true:

1. Strict signed-envelope mode is available and enabled for internet-facing peers.
2. Node identity derivation and key binding are compatible with reference semantics (with compatibility bridge during migration).
3. Manifest/hash canonicalization is backed by `rid-lib`.
4. Conformance tests pass against both Octo peers and BlockScience reference behavior for core 5 endpoints.
5. Extension endpoints are clearly documented as non-core protocol conveniences.

## Sources

### BlockScience local sources

- `RegenAI/koi-research/sources/blockscience/koi-net/README.md` (endpoint set, event/state model, FUN semantics)
- `RegenAI/koi-research/sources/blockscience/koi-net/src/koi_net/server.py` (endpoint wiring and envelope handler usage)
- `RegenAI/koi-research/sources/blockscience/koi-net/src/koi_net/secure.py` (validation rules: key binding, signature, target check)
- `RegenAI/koi-research/sources/blockscience/koi-net/src/koi_net/network/behavior.py` (handshake behavior)
- `RegenAI/koi-research/sources/blockscience/koi-net/src/koi_net/lifecycle.py` (first-contact handshake bootstrap)
- `RegenAI/koi-research/sources/blockscience/koi-net/src/koi_net/network/resolver.py` (neighbor polling behavior)
- `RegenAI/koi-research/sources/blockscience/koi-net/src/koi_net/network/error_handler.py` (UnknownNode -> handshake)
- `RegenAI/koi-research/sources/blockscience/koi-net/src/koi_net/config.py` (reference node RID generation path)
- `RegenAI/koi-research/sources/blockscience/rid-lib/README.md` (RID semantics: references vs referents; manifest/bundle concepts)
- `RegenAI/koi-research/sources/blockscience/rid-lib/src/rid_lib/ext/manifest.py` (manifest fields and generation)
- `RegenAI/koi-research/sources/blockscience/rid-lib/src/rid_lib/ext/utils.py` (JCS canonical hash utility)
- `RegenAI/koi-research/sources/blockscience/blog-koi-net-protocol-preview.md` (RID reference framing in KOI-net context)
- `RegenAI/koi-research/sources/blockscience/blog-koi-network-protocol-interlay.md` (handshake/discovery framing, provenance/CAT direction)

### Octo implementation sources

- `koi-processor/api/koi_net_router.py` (current endpoint surface, request unwrapping, poll/fetch behavior)
- `koi-processor/api/koi_envelope.py` (current signature verification behavior)
- `koi-processor/api/node_identity.py` (current truncated node RID derivation)
- `koi-processor/api/koi_poller.py` (edge semantics, key-learning and handshake self-heal)
- `koi-processor/api/event_queue.py` (event queue and RID type extraction behavior)
- `koi-processor/migrations/039_koi_net_events.sql` (events/edges/nodes schema)
- `koi-processor/migrations/041_cross_references.sql` (cross-reference schema)
- `koi-processor/tests/test_koi_interop.py` (current unsigned-poll interop expectation)
- `docs/join-the-network.md` and `README.md` (current operator model/discovery guidance)

### External package sources

- `koi-net` on PyPI: https://pypi.org/project/koi-net/
- `rid-lib` on PyPI: https://pypi.org/project/rid-lib/
